"""Persistence operations for GitHub repositories."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from inciflow.persistence.models.repositories import Repository


def get_repository_by_github_id(
    session: Session, github_repo_id: int
) -> Repository | None:
    """Find a repository by its immutable GitHub ID."""
    statement = select(Repository).where(
        Repository.github_repo_id == github_repo_id
    )
    return session.scalar(statement)


def get_repository_by_full_name(
    session: Session, full_name: str
) -> Repository | None:
    """Find a repository by its owner/name identifier."""
    statement = select(Repository).where(
        Repository.full_name == full_name
    )
    return session.scalar(statement)


def upsert_repository(
    session: Session,
    *,
    github_repo_id: int,
    owner: str,
    name: str,
    full_name: str,
    default_branch: str = "main",
    is_active: bool = True,
) -> Repository:
    """Insert or refresh a repository using its GitHub ID.

    The caller owns transaction commit and rollback.
    """
    statement = (
        insert(Repository)
        .values(
            github_repo_id=github_repo_id,
            owner=owner,
            name=name,
            full_name=full_name,
            default_branch=default_branch,
            is_active=is_active,
        )
        .on_conflict_do_update(
            index_elements=[Repository.github_repo_id],
            set_={
                "owner": owner,
                "name": name,
                "full_name": full_name,
                "default_branch": default_branch,
                "is_active": is_active,
            },
        )
        .returning(Repository.id)
    )

    repository_id = session.scalar(statement)
    if repository_id is None:
        raise RuntimeError("Repository upsert returned no repository ID.")

    repository = session.get(Repository, repository_id, populate_existing=True)
    if repository is None:
        raise RuntimeError("Repository was not found after upsert.")

    return repository
