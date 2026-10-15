"""Unit tests for the ingestion application service."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from inciflow.ingestion.schemas import IssueIngest, RepositoryIngest
from inciflow.ingestion.service import ingest_repository_snapshot


def make_repository_data() -> RepositoryIngest:
    return RepositoryIngest(
        github_repo_id=12345,
        owner="example",
        name="sample",
        full_name="example/sample",
    )


def make_issue(issue_id: int, number: int) -> IssueIngest:
    return IssueIngest(
        github_issue_id=issue_id,
        issue_number=number,
        title=f"Issue {number}",
        state="open",
    )


@patch("inciflow.ingestion.service.upsert_issue")
@patch("inciflow.ingestion.service.upsert_repository")
def test_ingestion_upserts_repository_and_all_issues(
    mock_upsert_repository: MagicMock,
    mock_upsert_issue: MagicMock,
) -> None:
    session = MagicMock()
    repository_id = uuid4()
    mock_upsert_repository.return_value.id = repository_id

    result = ingest_repository_snapshot(
        session,
        repository_data=make_repository_data(),
        issues=[make_issue(101, 1), make_issue(102, 2)],
    )

    session.begin.assert_called_once_with()
    mock_upsert_repository.assert_called_once()
    assert mock_upsert_issue.call_count == 2
    assert all(
        item.kwargs["repository_id"] == repository_id
        for item in mock_upsert_issue.call_args_list
    )
    assert result.repository_id == repository_id
    assert result.issue_count == 2
    assert result.synced_at.tzinfo is not None


@pytest.mark.parametrize(
    ("issues", "message"),
    [
        (
            [make_issue(101, 1), make_issue(101, 2)],
            "duplicate GitHub issue IDs",
        ),
        (
            [make_issue(101, 1), make_issue(102, 1)],
            "duplicate issue numbers",
        ),
    ],
)
def test_duplicate_snapshot_identity_is_rejected_before_transaction(
    issues: list[IssueIngest],
    message: str,
) -> None:
    session = MagicMock()

    with pytest.raises(ValueError, match=message):
        ingest_repository_snapshot(
            session,
            repository_data=make_repository_data(),
            issues=issues,
        )

    session.begin.assert_not_called()


@patch("inciflow.ingestion.service.upsert_issue")
@patch("inciflow.ingestion.service.upsert_repository")
def test_issue_failure_propagates_for_transaction_rollback(
    mock_upsert_repository: MagicMock,
    mock_upsert_issue: MagicMock,
) -> None:
    session = MagicMock()
    mock_upsert_repository.return_value.id = uuid4()
    mock_upsert_issue.side_effect = RuntimeError("Simulated persistence failure")

    with pytest.raises(RuntimeError, match="Simulated persistence failure"):
        ingest_repository_snapshot(
            session,
            repository_data=make_repository_data(),
            issues=[make_issue(101, 1)],
        )

    session.begin.assert_called_once_with()
