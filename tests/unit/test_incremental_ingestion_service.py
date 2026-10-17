
"""Unit tests for atomic incremental ingestion."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from inciflow.ingestion.schemas import IssueIngest, RepositoryIngest
from inciflow.ingestion.sync_service import (
    StaleCheckpointError,
    ingest_incremental_batch,
)


def make_repository() -> RepositoryIngest:
    """Build a repository payload for service tests."""
    return RepositoryIngest(
        github_repo_id=12345,
        owner="octo",
        name="widget",
        full_name="octo/widget",
        default_branch="main",
        is_active=True,
    )


def make_issue(
    *,
    github_issue_id: int = 90001,
    issue_number: int = 1,
    title: str = "Test issue",
) -> IssueIngest:
    """Build an issue payload for service tests."""
    return IssueIngest(
        github_issue_id=github_issue_id,
        issue_number=issue_number,
        title=title,
        body="Test body",
        state="open",
        author_login="octo-user",
        labels=["bug"],
    )


def make_session_with_repository_sync(
    *,
    cursor_payload: dict | None = None,
):
    """Build a mocked session and repository sync record."""
    session = MagicMock()
    repository = MagicMock()
    repository.id = uuid4()

    sync = MagicMock()
    sync.id = uuid4()
    sync.cursor_payload = (
        {} if cursor_payload is None else cursor_payload.copy()
    )
    sync.status = "pending"
    sync.last_synced_at = None
    sync.external_updated_at = None

    return session, repository, sync


def test_persists_batch_and_advances_checkpoint():
    session, repository, sync = make_session_with_repository_sync()

    with (
        patch(
            "inciflow.ingestion.sync_service.upsert_repository",
            return_value=repository,
        ),
        patch(
            "inciflow.ingestion.sync_service.lock_github_repository_sync",
            return_value=sync,
        ),
        patch(
            "inciflow.ingestion.sync_service.upsert_issue",
        ) as upsert_issue,
    ):
        result = ingest_incremental_batch(
            session,
            repository_data=make_repository(),
            issues=[make_issue()],
            expected_cursor_payload={},
            cursor_payload={"mode": "backfill", "page": 2},
            completed=False,
        )

    assert result.repository_id == repository.id
    assert result.sync_id == sync.id
    assert result.issue_count == 1
    assert result.completed is False
    assert sync.cursor_payload == {"mode": "backfill", "page": 2}
    assert sync.status == "pending"
    assert sync.last_synced_at is None
    upsert_issue.assert_called_once()


def test_completed_batch_marks_sync_as_synced():
    session, repository, sync = make_session_with_repository_sync(
        cursor_payload={"mode": "backfill", "page": 1}
    )

    with (
        patch(
            "inciflow.ingestion.sync_service.upsert_repository",
            return_value=repository,
        ),
        patch(
            "inciflow.ingestion.sync_service.lock_github_repository_sync",
            return_value=sync,
        ),
        patch("inciflow.ingestion.sync_service.upsert_issue"),
    ):
        result = ingest_incremental_batch(
            session,
            repository_data=make_repository(),
            issues=[make_issue()],
            expected_cursor_payload={"mode": "backfill", "page": 1},
            cursor_payload={
                "mode": "backfill",
                "page": 1,
                "completed": True,
            },
            completed=True,
        )

    assert result.completed is True
    assert sync.status == "synced"
    assert sync.cursor_payload == {
        "mode": "backfill",
        "page": 1,
        "completed": True,
    }
    assert sync.last_synced_at is not None


def test_completed_batch_persists_external_updated_at():
    session, repository, sync = make_session_with_repository_sync(
        cursor_payload={"mode": "backfill", "page": 1}
    )
    external_updated_at = datetime(2026, 1, 2, tzinfo=UTC)

    with (
        patch(
            "inciflow.ingestion.sync_service.upsert_repository",
            return_value=repository,
        ),
        patch(
            "inciflow.ingestion.sync_service.lock_github_repository_sync",
            return_value=sync,
        ),
        patch("inciflow.ingestion.sync_service.upsert_issue"),
    ):
        result = ingest_incremental_batch(
            session,
            repository_data=make_repository(),
            issues=[make_issue()],
            expected_cursor_payload={"mode": "backfill", "page": 1},
            cursor_payload={
                "mode": "backfill",
                "page": 1,
                "completed": True,
            },
            completed=True,
            external_updated_at=external_updated_at,
        )

    assert result.completed is True
    assert sync.status == "synced"
    assert sync.external_updated_at == external_updated_at


def test_stale_checkpoint_is_rejected_before_issue_upsert():
    session, repository, sync = make_session_with_repository_sync(
        cursor_payload={"mode": "backfill", "page": 2}
    )

    with (
        patch(
            "inciflow.ingestion.sync_service.upsert_repository",
            return_value=repository,
        ),
        patch(
            "inciflow.ingestion.sync_service.lock_github_repository_sync",
            return_value=sync,
        ),
        patch(
            "inciflow.ingestion.sync_service.upsert_issue"
        ) as upsert_issue,
        pytest.raises(
            StaleCheckpointError,
            match="Stored checkpoint changed",
        ),
    ):
        ingest_incremental_batch(
            session,
            repository_data=make_repository(),
            issues=[make_issue()],
            expected_cursor_payload={},
            cursor_payload={"mode": "backfill", "page": 2},
            completed=False,
        )

    upsert_issue.assert_not_called()


@pytest.mark.parametrize(
    "issues",
    [
        [
            make_issue(github_issue_id=90001, issue_number=1),
            make_issue(github_issue_id=90001, issue_number=2),
        ],
        [
            make_issue(github_issue_id=90001, issue_number=1),
            make_issue(github_issue_id=90002, issue_number=1),
        ],
    ],
)
def test_rejects_duplicate_issue_identifiers(issues):
    session = MagicMock()

    with pytest.raises(ValueError, match="duplicate"):
        ingest_incremental_batch(
            session,
            repository_data=make_repository(),
            issues=issues,
            expected_cursor_payload={},
            cursor_payload={"mode": "backfill", "page": 2},
            completed=False,
        )

    session.begin.assert_not_called()


def test_rejects_naive_external_updated_at():
    session = MagicMock()

    with pytest.raises(
        ValueError,
        match="external_updated_at must be timezone-aware",
    ):
        ingest_incremental_batch(
            session,
            repository_data=make_repository(),
            issues=[],
            expected_cursor_payload={},
            cursor_payload={"mode": "backfill", "page": 2},
            completed=False,
            external_updated_at=datetime(2026, 1, 1),
        )

    session.begin.assert_not_called()


def test_rejects_batches_over_500_issues():
    session = MagicMock()
    issues = [
        make_issue(
            github_issue_id=100000 + index,
            issue_number=index + 1,
        )
        for index in range(501)
    ]

    with pytest.raises(ValueError, match="cannot exceed 500"):
        ingest_incremental_batch(
            session,
            repository_data=make_repository(),
            issues=issues,
            expected_cursor_payload={},
            cursor_payload={"mode": "backfill", "page": 2},
            completed=False,
        )

    session.begin.assert_not_called()


def test_rejects_non_dictionary_checkpoint_payloads():
    session = MagicMock()

    with pytest.raises(TypeError, match="expected_cursor_payload"):
        ingest_incremental_batch(
            session,
            repository_data=make_repository(),
            issues=[],
            expected_cursor_payload=None,
            cursor_payload={},
            completed=False,
        )

    session.begin.assert_not_called()

    with pytest.raises(TypeError, match="cursor_payload"):
        ingest_incremental_batch(
            session,
            repository_data=make_repository(),
            issues=[],
            expected_cursor_payload={},
            cursor_payload=None,
            completed=False,
        )

    session.begin.assert_not_called()


def test_repository_schema_rejects_invalid_full_name():
    with pytest.raises(
        ValueError,
        match="full_name must use the owner/repository format",
    ):
        RepositoryIngest(
            github_repo_id=12345,
            owner="octo",
            name="widget",
            full_name="octo/widget/extra",
        )


@pytest.mark.parametrize(
    "field",
    [
        "created_at_github",
        "updated_at_github",
        "closed_at_github",
    ],
)
def test_issue_schema_rejects_naive_github_timestamps(field):
    from pydantic import ValidationError

    payload = {
        "github_issue_id": 90001,
        "issue_number": 1,
        "title": "Test issue",
        "state": "open",
        field: datetime(2026, 10, 16, 12, 0),
    }

    with pytest.raises(
        ValidationError,
        match="GitHub timestamps must include a timezone",
    ):
        IssueIngest(**payload)
