"""Persistence operations for external integration synchronization state."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from inciflow.persistence.models.integrations import IntegrationSync


def get_or_create_github_repository_sync(
    session: Session,
    *,
    github_repository_id: int,
) -> IntegrationSync:
    """Get or create durable inbound sync state for a GitHub repository.

    The caller owns transaction commit and rollback.
    """
    if github_repository_id <= 0:
        raise ValueError("github_repository_id must be positive.")

    statement = (
        insert(IntegrationSync)
        .values(
            integration_name="github",
            entity_type="repository",
            entity_id=str(github_repository_id),
            direction="inbound",
            status="pending",
            cursor_payload={},
        )
        .on_conflict_do_nothing(
            constraint="uq_integration_sync_entity_direction"
        )
        .returning(IntegrationSync.id)
    )

    sync_id = session.scalar(statement)

    if sync_id is None:
        # A conflicting record already exists. Resolve it by its natural key.
        sync_id = session.scalar(
            select(IntegrationSync.id).where(
                IntegrationSync.integration_name == "github",
                IntegrationSync.entity_type == "repository",
                IntegrationSync.entity_id == str(github_repository_id),
                IntegrationSync.direction == "inbound",
            )
        )

    if sync_id is None:
        raise RuntimeError("Could not retrieve GitHub repository sync state.")

    sync = session.get(IntegrationSync, sync_id, populate_existing=True)

    if sync is None:
        raise RuntimeError("GitHub repository sync state was not found.")

    return sync


def lock_github_repository_sync(
    session: Session,
    *,
    github_repository_id: int,
) -> IntegrationSync:
    """Get or create and lock a repository sync row."""
    if github_repository_id <= 0:
        raise ValueError("github_repository_id must be positive.")

    sync = get_or_create_github_repository_sync(
        session,
        github_repository_id=github_repository_id,
    )

    statement = (
        select(IntegrationSync)
        .where(IntegrationSync.id == sync.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )

    locked_sync = session.scalar(statement)

    if locked_sync is None:
        raise RuntimeError("Could not lock GitHub repository sync state.")

    return locked_sync


def mark_github_repository_sync_failed(
    session: Session,
    *,
    github_repository_id: int,
    error_message: str,
    started_at: datetime,
) -> IntegrationSync | None:
    """Record a failure unless a newer successful sync already exists.

    The caller owns the transaction. This function does not commit.
    """
    if github_repository_id <= 0:
        raise ValueError("github_repository_id must be positive.")

    if started_at.tzinfo is None or started_at.utcoffset() is None:
        raise ValueError("started_at must be timezone-aware.")

    statement = (
        select(IntegrationSync)
        .where(
            IntegrationSync.integration_name == "github",
            IntegrationSync.entity_type == "repository",
            IntegrationSync.entity_id == str(github_repository_id),
            IntegrationSync.direction == "inbound",
        )
        .with_for_update()
    )

    sync = session.scalar(statement)

    if sync is None:
        return None

    # Avoid overwriting a successful sync that completed after this attempt began.
    if (
        sync.last_synced_at is not None
        and sync.last_synced_at >= started_at
    ):
        return sync

    sync.status = "failed"
    sync.last_error = error_message

    return sync
