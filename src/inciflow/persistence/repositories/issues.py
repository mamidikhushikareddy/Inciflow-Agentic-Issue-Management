"""Persistence operations for GitHub issues."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from inciflow.persistence.models.issues import Issue


def get_issue_by_github_id(
    session: Session,
    *,
    repository_id: UUID,
    github_issue_id: int,
) -> Issue | None:
    """Find an issue by its GitHub ID within a repository."""
    statement = select(Issue).where(
        Issue.repository_id == repository_id,
        Issue.github_issue_id == github_issue_id,
    )
    return session.scalar(statement)


def list_issues(
    session: Session,
    *,
    repository_id: UUID,
    state: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Issue]:
    """List issues in stable, paginated order."""
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    if offset < 0:
        raise ValueError("offset cannot be negative")

    statement = select(Issue).where(
        Issue.repository_id == repository_id
    )
    if state is not None:
        statement = statement.where(Issue.state == state)

    statement = (
        statement.order_by(Issue.issue_number.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(session.scalars(statement).all())


def upsert_issue(
    session: Session,
    *,
    repository_id: UUID,
    github_issue_id: int,
    issue_number: int,
    title: str,
    body: str | None = None,
    state: str = "open",
    author_login: str | None = None,
    labels: list | None = None,
    created_at_github: datetime | None = None,
    updated_at_github: datetime | None = None,
    closed_at_github: datetime | None = None,
    last_synced_at: datetime | None = None,
) -> Issue:
    """Insert or refresh an issue using its repository and GitHub ID.

    The caller owns transaction commit and rollback.
    """
    normalized_labels = labels if labels is not None else []

    statement = (
        insert(Issue)
        .values(
            repository_id=repository_id,
            github_issue_id=github_issue_id,
            issue_number=issue_number,
            title=title,
            body=body,
            state=state,
            author_login=author_login,
            labels=normalized_labels,
            created_at_github=created_at_github,
            updated_at_github=updated_at_github,
            closed_at_github=closed_at_github,
            last_synced_at=last_synced_at,
        )
        .on_conflict_do_update(
            constraint="uq_issues_repository_id_github_issue_id",
            set_={
                "issue_number": issue_number,
                "title": title,
                "body": body,
                "state": state,
                "author_login": author_login,
                "labels": normalized_labels,
                "created_at_github": created_at_github,
                "updated_at_github": updated_at_github,
                "closed_at_github": closed_at_github,
                "last_synced_at": last_synced_at,
            },
        )
        .returning(Issue.id)
    )

    issue_id = session.scalar(statement)
    if issue_id is None:
        raise RuntimeError("Issue upsert returned no issue ID.")

    issue = session.get(Issue, issue_id, populate_existing=True)
    if issue is None:
        raise RuntimeError("Issue was not found after upsert.")

    return issue
