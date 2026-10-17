
"""Unit tests for GitHub issue batch checkpoint validation."""

from unittest.mock import Mock, patch

import pytest

from inciflow.ingestion.schemas import GitHubIssueBatch
from inciflow.ingestion.sync_service import ingest_github_issue_batch


def make_batch(
    *,
    expected_cursor_payload: dict,
    cursor_payload: dict,
    completed: bool,
) -> GitHubIssueBatch:
    """Build a valid-schema batch with the specified checkpoint transition."""
    return GitHubIssueBatch(
        repository={
            "github_repo_id": 12345,
            "owner": "octo",
            "name": "widget",
            "full_name": "octo/widget",
            "default_branch": "main",
            "is_active": True,
        },
        issues=[],
        expected_cursor_payload=expected_cursor_payload,
        cursor_payload=cursor_payload,
        completed=completed,
    )


def test_valid_incomplete_batch_delegates_to_atomic_persistence() -> None:
    session = Mock()
    batch = make_batch(
        expected_cursor_payload={},
        cursor_payload={"mode": "backfill", "page": 2},
        completed=False,
    )

    with patch(
        "inciflow.ingestion.sync_service.ingest_incremental_batch"
    ) as persist:
        result = ingest_github_issue_batch(session, batch=batch)

    persist.assert_called_once_with(
        session,
        repository_data=batch.repository,
        issues=batch.issues,
        expected_cursor_payload={},
        cursor_payload={"mode": "backfill", "page": 2},
        completed=False,
        external_updated_at=None,
    )
    assert result is persist.return_value


def test_valid_completed_batch_delegates_to_atomic_persistence() -> None:
    session = Mock()
    batch = make_batch(
        expected_cursor_payload={"mode": "backfill", "page": 2},
        cursor_payload={
            "mode": "backfill",
            "page": 2,
            "completed": True,
        },
        completed=True,
    )

    with patch(
        "inciflow.ingestion.sync_service.ingest_incremental_batch"
    ) as persist:
        result = ingest_github_issue_batch(session, batch=batch)

    persist.assert_called_once_with(
        session,
        repository_data=batch.repository,
        issues=batch.issues,
        expected_cursor_payload={"mode": "backfill", "page": 2},
        cursor_payload={
            "mode": "backfill",
            "page": 2,
            "completed": True,
        },
        completed=True,
        external_updated_at=None,
    )
    assert result is persist.return_value


@pytest.mark.parametrize(
    ("expected", "cursor", "completed"),
    [
        (
            {},
            {"mode": "backfill", "page": 1},
            False,
        ),
        (
            {"mode": "backfill", "page": 1},
            {"mode": "backfill", "page": 1},
            False,
        ),
        (
            {"mode": "backfill", "page": 2},
            {"mode": "backfill", "page": 2},
            True,
        ),
        (
            {"mode": "backfill", "page": 2},
            {"mode": "backfill", "page": 4},
            False,
        ),
    ],
)
def test_invalid_checkpoint_transition_is_rejected(
    expected: dict,
    cursor: dict,
    completed: bool,
) -> None:
    session = Mock()
    batch = make_batch(
        expected_cursor_payload=expected,
        cursor_payload=cursor,
        completed=completed,
    )

    with (
        patch(
            "inciflow.ingestion.sync_service.ingest_incremental_batch"
        ) as persist,
        pytest.raises(ValueError),
    ):
        ingest_github_issue_batch(session, batch=batch)

    persist.assert_not_called()


@pytest.mark.parametrize(
    ("expected", "cursor", "completed"),
    [
        (
            {"mode": "backfill", "page": 1, "unexpected": "value"},
            {"mode": "backfill", "page": 2},
            False,
        ),
        (
            {"mode": "backfill", "page": 1, "completed": False},
            {"mode": "backfill", "page": 2},
            False,
        ),
        (
            {"mode": "backfill", "page": 1},
            {"mode": "backfill", "page": 2, "unexpected": "value"},
            False,
        ),
        (
            {"mode": "backfill", "page": 1},
            {"mode": "backfill", "page": 2, "completed": False},
            False,
        ),
    ],
)
def test_checkpoint_payloads_reject_unexpected_fields(
    expected: dict,
    cursor: dict,
    completed: bool,
) -> None:
    session = Mock()
    batch = make_batch(
        expected_cursor_payload=expected,
        cursor_payload=cursor,
        completed=completed,
    )

    with (
        patch(
            "inciflow.ingestion.sync_service.ingest_incremental_batch"
        ) as persist,
        pytest.raises(ValueError),
    ):
        ingest_github_issue_batch(session, batch=batch)

    persist.assert_not_called()
