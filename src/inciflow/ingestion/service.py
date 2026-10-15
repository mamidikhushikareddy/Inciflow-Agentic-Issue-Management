"""Transactional application service for GitHub repository ingestion."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from inciflow.ingestion.schemas import IssueIngest, RepositoryIngest
from inciflow.persistence.repositories.issues import upsert_issue
from inciflow.persistence.repositories.repositories import upsert_repository


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Summary of a successfully committed repository snapshot."""

    repository_id: UUID
    issue_count: int
    synced_at: datetime


def ingest_repository_snapshot(
    session: Session,
    *,
    repository_data: RepositoryIngest,
    issues: list[IssueIngest],
) -> IngestionResult:
    """Upsert a repository and its issues atomically.

    The supplied session must not already have an active transaction.
    This service owns the transaction: all changes commit together, or
    the transaction rolls back if any operation fails.
    """
    github_issue_ids = [issue.github_issue_id for issue in issues]
    if len(github_issue_ids) != len(set(github_issue_ids)):
        raise ValueError("Snapshot contains duplicate GitHub issue IDs.")

    issue_numbers = [issue.issue_number for issue in issues]
    if len(issue_numbers) != len(set(issue_numbers)):
        raise ValueError("Snapshot contains duplicate issue numbers.")

    synced_at = datetime.now(UTC)

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

        for issue_data in issues:
            upsert_issue(
                session,
                repository_id=repository.id,
                **issue_data.model_dump(),
                last_synced_at=synced_at,
            )

        repository_id = repository.id

    return IngestionResult(
        repository_id=repository_id,
        issue_count=len(issues),
        synced_at=synced_at,
    )
