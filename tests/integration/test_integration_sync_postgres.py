"""PostgreSQL integration tests for durable integration sync state."""

from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from inciflow.core.config import settings
from inciflow.persistence.database import get_engine
from inciflow.persistence.models.integrations import IntegrationSync
from inciflow.persistence.repositories.integration_syncs import (
    get_or_create_github_repository_sync,
)


@pytest.fixture
def db_session():
    """Provide a rollback-isolated session against inciflow_test only."""
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

    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection, expire_on_commit=False)
        try:
            yield session
        finally:
            session.close()
            if transaction.is_active:
                transaction.rollback()


def test_github_sync_state_is_reused_and_preserves_checkpoint(db_session):
    github_repository_id = uuid4().int % 1_000_000_000_000 + 1

    first = get_or_create_github_repository_sync(
        db_session,
        github_repository_id=github_repository_id,
    )

    first_id = first.id
    first.cursor_payload = {
        "mode": "incremental",
        "updated_since": "2026-10-15T10:00:00+00:00",
    }
    first.status = "synced"
    db_session.flush()

    second = get_or_create_github_repository_sync(
        db_session,
        github_repository_id=github_repository_id,
    )

    assert second.id == first_id
    assert second.integration_name == "github"
    assert second.entity_type == "repository"
    assert second.entity_id == str(github_repository_id)
    assert second.direction == "inbound"
    assert second.status == "synced"
    assert second.cursor_payload == {
        "mode": "incremental",
        "updated_since": "2026-10-15T10:00:00+00:00",
    }


def test_github_sync_state_does_not_commit_callers_transaction(db_session):
    github_repository_id = uuid4().int % 1_000_000_000_000 + 1

    sync = get_or_create_github_repository_sync(
        db_session,
        github_repository_id=github_repository_id,
    )
    sync_id = sync.id

    # The fixture owns the outer transaction; this repository must not commit it.
    assert db_session.in_transaction()

    db_session.rollback()

    with Session(get_engine()) as verification_session:
        persisted = verification_session.scalar(
            select(IntegrationSync).where(
                IntegrationSync.id == sync_id
            )
        )

    assert persisted is None
