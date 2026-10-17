
"""Atomic persistence for incremental GitHub issue synchronization."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from inciflow.ingestion.checkpoints import advance_incremental_checkpoint
from inciflow.ingestion.schemas import (
    GitHubIssueBatch,
    IssueIngest,
    RepositoryIngest,
)
from inciflow.persistence.repositories.integration_syncs import (
    lock_github_repository_sync,
)
from inciflow.persistence.repositories.issues import upsert_issue
from inciflow.persistence.repositories.repositories import upsert_repository


class StaleCheckpointError(RuntimeError):
    """Raised when a worker attempts to persist from an outdated checkpoint."""


@dataclass(frozen=True)
class IncrementalIngestionResult:
    """Summary of one successfully persisted incremental batch."""

    repository_id: UUID
    sync_id: UUID
    issue_count: int
    completed: bool
    persisted_at: datetime


def ingest_incremental_batch(
    session: Session,
    *,
    repository_data: RepositoryIngest,
    issues: list[IssueIngest],
    expected_cursor_payload: dict[str, Any],
    cursor_payload: dict[str, Any],
    completed: bool,
    external_updated_at: datetime | None = None,
) -> IncrementalIngestionResult:
    """Persist a batch and its continuation state atomically.

    The caller must provide a session without an active transaction.
    This service owns the transaction.
    """
    if len(issues) > 500:
        raise ValueError("Incremental batch cannot exceed 500 issues.")

    if not isinstance(expected_cursor_payload, dict):
        raise TypeError("expected_cursor_payload must be a dictionary.")

    if not isinstance(cursor_payload, dict):
        raise TypeError("cursor_payload must be a dictionary.")

    if external_updated_at is not None and (
        external_updated_at.tzinfo is None
        or external_updated_at.utcoffset() is None
    ):
        raise ValueError("external_updated_at must be timezone-aware.")

    github_issue_ids = [issue.github_issue_id for issue in issues]
    if len(github_issue_ids) != len(set(github_issue_ids)):
        raise ValueError("Batch contains duplicate GitHub issue IDs.")

    issue_numbers = [issue.issue_number for issue in issues]
    if len(issue_numbers) != len(set(issue_numbers)):
        raise ValueError("Batch contains duplicate issue numbers.")

    persisted_at = datetime.now(UTC)

    with session.begin():
        repository = upsert_repository(
            session,
            github_repo_id=repository_data.github_repo_id,
            owner=repository_data.owner,
            name=repository_data.name,
            full_name=repository_data.full_name,
            default_branch=repository_data.default_branch,
            is_active=repository_data.is_active,
        )

        sync = lock_github_repository_sync(
            session,
            github_repository_id=repository_data.github_repo_id,
        )

        if sync.cursor_payload != expected_cursor_payload:
            raise StaleCheckpointError(
                "Stored checkpoint changed since this batch was fetched."
            )

        for issue_data in issues:
            upsert_issue(
                session,
                repository_id=repository.id,
                **issue_data.model_dump(),
                last_synced_at=persisted_at,
            )

        sync.cursor_payload = cursor_payload
        sync.status = "synced" if completed else "pending"
        sync.last_error = None

        if completed:
            sync.last_synced_at = persisted_at
            if external_updated_at is not None:
                sync.external_updated_at = external_updated_at

        repository_id = repository.id
        sync_id = sync.id

    return IncrementalIngestionResult(
        repository_id=repository_id,
        sync_id=sync_id,
        issue_count=len(issues),
        completed=completed,
        persisted_at=persisted_at,
    )


def ingest_github_issue_batch(
    session: Session,
    *,
    batch: GitHubIssueBatch,
    external_updated_at: datetime | None = None,
) -> IncrementalIngestionResult:
    """Validate and atomically persist a GitHub backfill batch."""
    expected = batch.expected_cursor_payload
    cursor = batch.cursor_payload

    if not isinstance(expected, dict) or not isinstance(cursor, dict):
        raise TypeError("Checkpoint payloads must be dictionaries.")

    # An empty checkpoint represents the initial backfill request.
    if expected == {}:
        fetched_page = 1
    else:
        if (
            set(expected)
            not in (
                {"mode", "page"},
                {"mode", "page", "after"},
            )
            or expected.get("mode") != "backfill"
            or type(expected.get("page")) is not int
            or expected["page"] < 1
            or (
                "after" in expected
                and (
                    not isinstance(expected["after"], str)
                    or not expected["after"]
                )
            )
        ):
            raise ValueError("Invalid expected backfill checkpoint.")

        fetched_page = expected["page"]

    if batch.completed:
        if (
            set(cursor) != {"mode", "page", "completed"}
            or cursor.get("mode") != "backfill"
            or type(cursor.get("page")) is not int
            or cursor["page"] < 1
            or cursor.get("completed") is not True
        ):
            raise ValueError("Invalid completed backfill checkpoint.")
    else:
        if (
            set(cursor)
            not in (
                {"mode", "page"},
                {"mode", "page", "after"},
            )
            or cursor.get("mode") != "backfill"
            or type(cursor.get("page")) is not int
            or cursor["page"] < 1
            or (
                "after" in cursor
                and (
                    not isinstance(cursor["after"], str)
                    or not cursor["after"]
                )
            )
        ):
            raise ValueError("Invalid incomplete backfill checkpoint.")

    expected_next_page = (
        fetched_page if batch.completed else fetched_page + 1
    )

    if cursor["page"] != expected_next_page:
        raise ValueError("Backfill checkpoint does not match the fetched page.")

    return ingest_incremental_batch(
        session,
        repository_data=batch.repository,
        issues=batch.issues,
        expected_cursor_payload=expected,
        cursor_payload=cursor,
        completed=batch.completed,
        external_updated_at=external_updated_at,
    )


def ingest_updated_issue_batch(
    session: Session,
    *,
    repository_data: RepositoryIngest,
    issues: list[IssueIngest],
    expected_cursor_payload: dict[str, Any],
    expected_watermark: datetime | None,
    new_watermark: datetime,
    overlap_seconds: int = 120,
) -> IncrementalIngestionResult:
    """Persist an updated-issues batch and advance its watermark atomically."""
    cursor_payload = advance_incremental_checkpoint(
        current_payload=expected_cursor_payload,
        expected_watermark=expected_watermark,
        new_watermark=new_watermark,
        overlap_seconds=overlap_seconds,
    )

    return ingest_incremental_batch(
        session,
        repository_data=repository_data,
        issues=issues,
        expected_cursor_payload=expected_cursor_payload,
        cursor_payload=cursor_payload,
        completed=True,
        external_updated_at=new_watermark,
    )
