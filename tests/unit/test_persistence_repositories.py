"""Isolated tests for persistence repository behavior."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from inciflow.persistence.repositories.issues import (
    list_issues,
    upsert_issue,
)
from inciflow.persistence.repositories.repositories import (
    upsert_repository,
)


def test_list_issues_rejects_invalid_limit_before_database_access():
    session = MagicMock()

    with pytest.raises(ValueError, match="limit must be between"):
        list_issues(session, repository_id=uuid4(), limit=0)

    session.execute.assert_not_called()
    session.scalars.assert_not_called()


def test_list_issues_rejects_negative_offset_before_database_access():
    session = MagicMock()

    with pytest.raises(ValueError, match="offset cannot be negative"):
        list_issues(session, repository_id=uuid4(), offset=-1)

    session.execute.assert_not_called()
    session.scalars.assert_not_called()


def test_repository_upsert_uses_github_id_conflict_target():
    session = MagicMock()
    repository_id = uuid4()
    expected_repository = MagicMock()
    session.scalar.return_value = repository_id
    session.get.return_value = expected_repository

    result = upsert_repository(
        session,
        github_repo_id=123456,
        owner="example",
        name="sample",
        full_name="example/sample",
    )

    statement = session.scalar.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "ON CONFLICT (github_repo_id)" in sql
    assert result is expected_repository
    session.get.assert_called_once_with(
        __import__(
            "inciflow.persistence.models.repositories",
            fromlist=["Repository"],
        ).Repository,
        repository_id,
        populate_existing=True,
    )
    session.commit.assert_not_called()


def test_issue_upsert_uses_repository_and_github_issue_identity():
    session = MagicMock()
    issue_id = uuid4()
    repository_id = uuid4()
    expected_issue = MagicMock()
    session.scalar.return_value = issue_id
    session.get.return_value = expected_issue

    result = upsert_issue(
        session,
        repository_id=repository_id,
        github_issue_id=987654,
        issue_number=42,
        title="Example issue",
        labels=["bug"],
    )

    statement = session.scalar.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "ON CONFLICT ON CONSTRAINT uq_issues_repository_id_github_issue_id" in sql
    assert result is expected_issue
    session.commit.assert_not_called()


def test_issue_upsert_returns_error_if_insert_returns_no_id():
    session = MagicMock()
    session.scalar.return_value = None

    with pytest.raises(RuntimeError, match="Issue upsert returned no issue ID"):
        upsert_issue(
            session,
            repository_id=uuid4(),
            github_issue_id=987654,
            issue_number=42,
            title="Example issue",
        )

    session.get.assert_not_called()
    session.commit.assert_not_called()
