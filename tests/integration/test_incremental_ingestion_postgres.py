"""PostgreSQL integration tests for incremental ingestion."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from inciflow.core.config import settings
from inciflow.ingestion.schemas import IssueIngest, RepositoryIngest
from inciflow.ingestion.sync_service import (
    StaleCheckpointError,
    ingest_incremental_batch,
    ingest_updated_issue_batch,
)
from inciflow.persistence.database import get_engine
from inciflow.persistence.models.integrations import IntegrationSync
from inciflow.persistence.models.issues import Issue
from inciflow.persistence.models.repositories import Repository


@pytest.fixture
def github_repository_id() -> int:
    """Generate a repository ID unlikely to collide with another test."""
    return uuid4().int % 1_000_000_000_000 + 1


@pytest.fixture
def isolated_database(github_repository_id: int):
    """Restrict integration tests to inciflow_test and clean up test data."""
    if settings.database_name != "inciflow_test":
        pytest.skip("PostgreSQL integration tests require inciflow_test.")

    engine = get_engine()

    with engine.connect() as connection:
        actual_database = connection.scalar(
            text("SELECT current_database()")
        )

    if actual_database != "inciflow_test":
        pytest.fail(
            f"Safety check failed: connected to {actual_database!r}, "
            "not inciflow_test."
        )

    try:
        yield github_repository_id
    finally:
        # The service commits its own transaction, so cleanup must use
        # a separate transaction after each test.
        with Session(engine) as cleanup_session, cleanup_session.begin():
            repository = cleanup_session.scalar(
                select(Repository).where(
                    Repository.github_repo_id == github_repository_id
                )
            )

            if repository is not None:
                cleanup_session.execute(
                    delete(IntegrationSync).where(
                        IntegrationSync.integration_name == "github",
                        IntegrationSync.entity_type == "repository",
                        IntegrationSync.entity_id
                        == str(github_repository_id),
                        IntegrationSync.direction == "inbound",
                    )
                )
                cleanup_session.execute(
                    delete(Issue).where(
                        Issue.repository_id == repository.id
                    )
                )
                cleanup_session.delete(repository)


def make_repository(github_repository_id: int) -> RepositoryIngest:
    """Build a repository payload for an integration test."""
    return RepositoryIngest(
        github_repo_id=github_repository_id,
        owner="inciflow-integration-test",
        name=f"repo-{github_repository_id}",
        full_name=f"inciflow-integration-test/repo-{github_repository_id}",
        default_branch="main",
    )


def make_issue(
    github_issue_id: int,
    issue_number: int,
    *,
    title: str = "Initial title",
) -> IssueIngest:
    """Build an issue payload for an integration test."""
    return IssueIngest(
        github_issue_id=github_issue_id,
        issue_number=issue_number,
        title=title,
        body="Integration test issue",
        state="open",
        labels=["integration-test"],
    )


def test_incremental_batch_persists_issue_and_checkpoint(
    isolated_database: int,
):
    """Persist the issue and completed sync checkpoint together."""
    engine = get_engine()
    repository_data = make_repository(isolated_database)
    issue_github_id = isolated_database + 1

    with Session(engine) as ingestion_session:
        result = ingest_incremental_batch(
            ingestion_session,
            repository_data=repository_data,
            issues=[make_issue(issue_github_id, 1)],
            expected_cursor_payload={},
            cursor_payload={"mode": "incremental", "page": 1},
            completed=True,
        )

    with Session(engine) as verification_session:
        repository = verification_session.scalar(
            select(Repository).where(
                Repository.github_repo_id == isolated_database
            )
        )
        assert repository is not None

        issue = verification_session.scalar(
            select(Issue).where(
                Issue.repository_id == repository.id,
                Issue.github_issue_id == issue_github_id,
            )
        )
        sync = verification_session.scalar(
            select(IntegrationSync).where(
                IntegrationSync.integration_name == "github",
                IntegrationSync.entity_type == "repository",
                IntegrationSync.entity_id == str(isolated_database),
                IntegrationSync.direction == "inbound",
            )
        )

        assert issue is not None
        assert issue.title == "Initial title"
        assert sync is not None
        assert sync.status == "synced"
        assert sync.cursor_payload == {"mode": "incremental", "page": 1}
        assert sync.last_synced_at is not None

    assert result.issue_count == 1
    assert result.completed is True


def test_replaying_batch_updates_issue_without_duplicates(
    isolated_database: int,
):
    """Replaying an issue updates its existing row instead of duplicating it."""
    engine = get_engine()
    repository_data = make_repository(isolated_database)
    issue_github_id = isolated_database + 1

    with Session(engine) as first_session:
        first_result = ingest_incremental_batch(
            first_session,
            repository_data=repository_data,
            issues=[
                make_issue(
                    issue_github_id,
                    1,
                    title="Original title",
                )
            ],
            expected_cursor_payload={},
            cursor_payload={"page": 1},
            completed=False,
        )

    with Session(engine) as second_session:
        second_result = ingest_incremental_batch(
            second_session,
            repository_data=repository_data,
            issues=[
                make_issue(
                    issue_github_id,
                    1,
                    title="Updated title",
                )
            ],
            expected_cursor_payload={"page": 1},
            cursor_payload={"page": 1},
            completed=True,
        )

    with Session(engine) as verification_session:
        repository = verification_session.scalar(
            select(Repository).where(
                Repository.github_repo_id == isolated_database
            )
        )
        assert repository is not None

        issues = list(
            verification_session.scalars(
                select(Issue).where(
                    Issue.repository_id == repository.id,
                    Issue.github_issue_id == issue_github_id,
                )
            ).all()
        )
        assert len(issues) == 1
        assert issues[0].title == "Updated title"

        sync = verification_session.scalar(
            select(IntegrationSync).where(
                IntegrationSync.integration_name == "github",
                IntegrationSync.entity_type == "repository",
                IntegrationSync.entity_id == str(isolated_database),
                IntegrationSync.direction == "inbound",
            )
        )
        assert sync is not None
        assert sync.status == "synced"
        assert sync.cursor_payload == {"page": 1}

    assert first_result.issue_count == 1
    assert second_result.issue_count == 1
    assert first_result.completed is False
    assert second_result.completed is True


def test_mid_batch_failure_rolls_back_all_ingestion_writes(
    isolated_database: int,
):
    """A mid-batch failure must roll back repository and issue writes."""
    from unittest.mock import patch

    from inciflow.persistence.repositories.issues import (
        upsert_issue as real_upsert_issue,
    )

    engine = get_engine()
    repository_data = make_repository(isolated_database)
    call_count = 0

    def fail_on_second_issue(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("Simulated mid-batch failure")
        return real_upsert_issue(*args, **kwargs)

    with (
        pytest.raises(RuntimeError, match="Simulated mid-batch failure"),
        Session(engine) as ingestion_session,
        patch(
            "inciflow.ingestion.sync_service.upsert_issue",
            side_effect=fail_on_second_issue,
        ),
    ):
        ingest_incremental_batch(
            ingestion_session,
            repository_data=repository_data,
            issues=[
                make_issue(
                    isolated_database + 1,
                    1,
                    title="First issue",
                ),
                make_issue(
                    isolated_database + 2,
                    2,
                    title="Second issue",
                ),
            ],
            expected_cursor_payload={},
            cursor_payload={"page": 2},
            completed=True,
        )

    assert call_count == 2

    with Session(engine) as verification_session:
        repository = verification_session.scalar(
            select(Repository).where(
                Repository.github_repo_id == isolated_database
            )
        )
        sync = verification_session.scalar(
            select(IntegrationSync).where(
                IntegrationSync.integration_name == "github",
                IntegrationSync.entity_type == "repository",
                IntegrationSync.entity_id == str(isolated_database),
                IntegrationSync.direction == "inbound",
            )
        )
        assert repository is None
        assert sync is None


def test_stale_checkpoint_rejects_batch_and_rolls_back_issue_writes(
    isolated_database: int,
):
    """Reject a stale worker without persisting its issue or checkpoint."""
    engine = get_engine()
    repository_data = make_repository(isolated_database)
    existing_issue_id = isolated_database + 1
    stale_issue_id = isolated_database + 2

    # Worker A advances the stored checkpoint.
    with Session(engine) as first_session:
        ingest_incremental_batch(
            first_session,
            repository_data=repository_data,
            issues=[
                make_issue(
                    existing_issue_id,
                    1,
                    title="Current issue",
                )
            ],
            expected_cursor_payload={},
            cursor_payload={"page": 1},
            completed=False,
        )

    # Worker B fetched from the old checkpoint and must be rejected.
    with (
        Session(engine) as stale_session,
        pytest.raises(
            StaleCheckpointError,
            match="Stored checkpoint changed",
        ),
    ):
        ingest_incremental_batch(
            stale_session,
            repository_data=repository_data,
            issues=[
                make_issue(
                    stale_issue_id,
                    2,
                    title="Stale issue",
                )
            ],
            expected_cursor_payload={},
            cursor_payload={"page": 2},
            completed=True,
        )

    # Verify the committed state is unchanged by the rejected batch.
    with Session(engine) as verification_session:
        repository = verification_session.scalar(
            select(Repository).where(
                Repository.github_repo_id == isolated_database
            )
        )
        assert repository is not None

        current_issue = verification_session.scalar(
            select(Issue).where(
                Issue.repository_id == repository.id,
                Issue.github_issue_id == existing_issue_id,
            )
        )
        stale_issue = verification_session.scalar(
            select(Issue).where(
                Issue.repository_id == repository.id,
                Issue.github_issue_id == stale_issue_id,
            )
        )
        sync = verification_session.scalar(
            select(IntegrationSync).where(
                IntegrationSync.integration_name == "github",
                IntegrationSync.entity_type == "repository",
                IntegrationSync.entity_id == str(isolated_database),
                IntegrationSync.direction == "inbound",
            )
        )

        assert current_issue is not None
        assert current_issue.title == "Current issue"
        assert stale_issue is None
        assert sync is not None
        assert sync.cursor_payload == {"page": 1}
        assert sync.status == "pending"


def test_updated_issue_batch_preserves_backfill_and_persists_watermark(
    isolated_database: int,
):
    """Recurring sync should preserve backfill state and store its watermark."""
    engine = get_engine()
    repository_data = make_repository(isolated_database)
    issue_github_id = isolated_database + 1
    watermark = datetime(2026, 10, 15, 15, 0, tzinfo=UTC)
    backfill_checkpoint = {
        "mode": "backfill",
        "page": 1,
        "completed": True,
    }

    with Session(engine) as backfill_session:
        ingest_incremental_batch(
            backfill_session,
            repository_data=repository_data,
            issues=[],
            expected_cursor_payload={},
            cursor_payload=backfill_checkpoint,
            completed=True,
        )

    with Session(engine) as recurring_session:
        result = ingest_updated_issue_batch(
            recurring_session,
            repository_data=repository_data,
            issues=[
                make_issue(
                    issue_github_id,
                    1,
                    title="Updated during recurring sync",
                )
            ],
            expected_cursor_payload=backfill_checkpoint,
            expected_watermark=None,
            new_watermark=watermark,
            overlap_seconds=120,
        )

    with Session(engine) as verification_session:
        repository = verification_session.scalar(
            select(Repository).where(
                Repository.github_repo_id == isolated_database
            )
        )
        assert repository is not None

        issue = verification_session.scalar(
            select(Issue).where(
                Issue.repository_id == repository.id,
                Issue.github_issue_id == issue_github_id,
            )
        )
        assert issue is not None
        assert issue.title == "Updated during recurring sync"

        sync = verification_session.scalar(
            select(IntegrationSync).where(
                IntegrationSync.integration_name == "github",
                IntegrationSync.entity_type == "repository",
                IntegrationSync.entity_id == str(isolated_database),
                IntegrationSync.direction == "inbound",
            )
        )
        assert sync is not None
        assert sync.cursor_payload == {
            **backfill_checkpoint,
            "updated_sync": {
                "watermark": watermark.isoformat(),
                "overlap_seconds": 120,
            },
        }
        assert sync.external_updated_at == watermark

    assert result.issue_count == 1
    assert result.completed is True
