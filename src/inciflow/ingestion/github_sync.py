"""Orchestration for recurring GitHub issue synchronization."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from inciflow.ingestion.sync_service import (
    IncrementalIngestionResult,
    ingest_updated_issue_batch,
)
from inciflow.integrations.github import GitHubClient
from inciflow.persistence.repositories.integration_syncs import (
    get_or_create_github_repository_sync,
)

DEFAULT_OVERLAP_SECONDS = 120


def sync_updated_github_issues(
    session: Session,
    *,
    owner: str,
    repository: str,
    github_client: GitHubClient,
    overlap_seconds: int = DEFAULT_OVERLAP_SECONDS,
    now: datetime | None = None,
) -> IncrementalIngestionResult:
    """Fetch updated GitHub issues and persist them with a durable watermark.

    Historical backfill must be completed before this recurring sync runs.

    GitHub requests happen outside database transactions. Checkpoint reads
    use a short transaction; issue persistence and checkpoint advancement
    are delegated to the atomic sync service.

    The supplied session must not already have an active transaction.
    """
    if (
        not isinstance(overlap_seconds, int)
        or isinstance(overlap_seconds, bool)
        or overlap_seconds < 0
    ):
        raise ValueError("overlap_seconds must be a non-negative integer.")

    watermark = now if now is not None else datetime.now(UTC)

    if not isinstance(watermark, datetime):
        raise TypeError("now must be a datetime.")

    if watermark.tzinfo is None or watermark.utcoffset() is None:
        raise ValueError("now must be timezone-aware.")

    watermark = watermark.astimezone(UTC)

    # Fetch repository metadata once, outside a database transaction.
    repository_data = github_client.fetch_repository(owner, repository)

    # Read the current checkpoint in a short transaction.
    with session.begin():
        sync = get_or_create_github_repository_sync(
            session,
            github_repository_id=repository_data.github_repo_id,
        )
        expected_cursor_payload = dict(sync.cursor_payload or {})
        expected_watermark = _read_watermark(expected_cursor_payload)

        # Recurring sync must not skip unfinished historical backfill.
        if (
            expected_cursor_payload.get("mode") != "backfill"
            or expected_cursor_payload.get("completed") is not True
        ):
            raise RuntimeError(
                "Historical GitHub issue backfill must be completed "
                "before recurring synchronization can run."
            )

    # Re-fetch an overlap to reduce the risk of missing boundary updates.
    since = watermark - timedelta(seconds=overlap_seconds)
    if expected_watermark is not None:
        since = expected_watermark - timedelta(seconds=overlap_seconds)

    batch = github_client.fetch_updated_issue_batch(
        owner,
        repository,
        since=since,
        watermark=watermark,
    )

    return ingest_updated_issue_batch(
        session,
        repository_data=batch.repository,
        issues=batch.issues,
        expected_cursor_payload=expected_cursor_payload,
        expected_watermark=expected_watermark,
        new_watermark=batch.watermark,
        overlap_seconds=overlap_seconds,
    )


def _read_watermark(cursor_payload: dict) -> datetime | None:
    """Read and validate the persisted recurring-sync watermark."""
    updated_sync = cursor_payload.get("updated_sync")

    if updated_sync is None:
        return None

    if not isinstance(updated_sync, dict):
        raise TypeError("Stored updated_sync checkpoint must be a dictionary.")

    value = updated_sync.get("watermark")

    if value is None:
        return None

    if not isinstance(value, str):
        raise TypeError("Stored watermark must be an ISO-8601 string.")

    try:
        watermark = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Stored watermark is not a valid timestamp.") from exc

    if watermark.tzinfo is None or watermark.utcoffset() is None:
        raise ValueError("Stored watermark must be timezone-aware.")

    return watermark.astimezone(UTC)
