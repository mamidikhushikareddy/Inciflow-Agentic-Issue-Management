"""Unit tests for integration synchronization persistence."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from inciflow.persistence.models.integrations import IntegrationSync
from inciflow.persistence.repositories.integration_syncs import (
    get_or_create_github_repository_sync,
)


def test_github_sync_record_uses_natural_key_and_conflict_safe_insert():
    session = MagicMock()
    sync_id = uuid4()
    expected_sync = MagicMock()
    session.scalar.return_value = sync_id
    session.get.return_value = expected_sync

    result = get_or_create_github_repository_sync(
        session, github_repository_id=12345
    )

    statement = session.scalar.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "ON CONFLICT ON CONSTRAINT uq_integration_sync_entity_direction" in sql
    assert result is expected_sync
    assert session.get.call_args.args == (IntegrationSync, sync_id)
    assert session.get.call_args.kwargs == {"populate_existing": True}
    session.commit.assert_not_called()


def test_existing_sync_record_is_looked_up_after_conflict():
    session = MagicMock()
    sync_id = uuid4()
    expected_sync = MagicMock()
    session.scalar.side_effect = [None, sync_id]
    session.get.return_value = expected_sync

    result = get_or_create_github_repository_sync(
        session, github_repository_id=12345
    )

    assert result is expected_sync
    assert session.scalar.call_count == 2
    lookup = session.scalar.call_args.args[0]
    sql = str(lookup.compile(dialect=postgresql.dialect()))

    assert "integration_syncs.integration_name" in sql
    assert "integration_syncs.entity_id" in sql
    assert "integration_syncs.direction" in sql
    session.commit.assert_not_called()


@pytest.mark.parametrize("repository_id", [0, -1])
def test_invalid_github_repository_id_is_rejected_before_database_access(
    repository_id: int,
):
    session = MagicMock()

    with pytest.raises(ValueError, match="must be positive"):
        get_or_create_github_repository_sync(
            session, github_repository_id=repository_id
        )

    session.scalar.assert_not_called()
    session.get.assert_not_called()
    session.commit.assert_not_called()


def test_missing_sync_record_raises_runtime_error():
    session = MagicMock()
    session.scalar.side_effect = [None, None]

    with pytest.raises(RuntimeError, match="Could not retrieve"):
        get_or_create_github_repository_sync(
            session, github_repository_id=12345
        )

    session.get.assert_not_called()
    session.commit.assert_not_called()


def test_missing_sync_object_after_id_resolution_raises_runtime_error():
    session = MagicMock()
    session.scalar.return_value = uuid4()
    session.get.return_value = None

    with pytest.raises(RuntimeError, match="was not found"):
        get_or_create_github_repository_sync(
            session, github_repository_id=12345
        )

    session.get.assert_called_once()
    session.commit.assert_not_called()


def test_lock_github_repository_sync_rejects_invalid_repository_id():
    from inciflow.persistence.repositories.integration_syncs import (
        lock_github_repository_sync,
    )

    session = MagicMock()

    with pytest.raises(ValueError, match="must be positive"):
        lock_github_repository_sync(session, github_repository_id=0)

    session.scalar.assert_not_called()
    session.get.assert_not_called()


def test_lock_github_repository_sync_raises_when_locked_row_is_missing():
    from inciflow.persistence.repositories.integration_syncs import (
        lock_github_repository_sync,
    )

    sync = MagicMock()
    sync.id = uuid4()
    session = MagicMock()
    session.scalar.side_effect = [sync, None]

    with pytest.raises(RuntimeError, match="Could not lock"):
        lock_github_repository_sync(session, github_repository_id=12345)

    assert session.scalar.call_count == 2
    lock_statement = session.scalar.call_args.args[0]
    sql = str(lock_statement.compile(dialect=postgresql.dialect()))

    assert "FOR UPDATE" in sql
    assert session.scalar.call_args.kwargs == {}
    session.commit.assert_not_called()


def test_lock_github_repository_sync_returns_locked_row():
    from inciflow.persistence.repositories.integration_syncs import (
        lock_github_repository_sync,
    )

    initial_sync = MagicMock()
    initial_sync.id = uuid4()
    locked_sync = MagicMock()
    session = MagicMock()
    session.scalar.side_effect = [initial_sync, locked_sync]

    result = lock_github_repository_sync(
        session, github_repository_id=12345
    )

    assert result is locked_sync
    assert session.scalar.call_count == 2

    lock_statement = session.scalar.call_args.args[0]
    sql = str(lock_statement.compile(dialect=postgresql.dialect()))

    assert "FOR UPDATE" in sql
    assert "populate_existing" in str(lock_statement._execution_options)
    session.commit.assert_not_called()
