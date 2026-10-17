"""Persistence operations for external integration synchronization state."""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from inciflow.persistence.models.integrations import IntegrationSync


def get_or_create_github_repository_sync(
    session: Session,
    *,
    github_repository_id: int,
) -> IntegrationSync:
    """Get or create the durable inbound sync state for a GitHub repository.

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
        from sqlalchemy import select

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
    from sqlalchemy import select

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
