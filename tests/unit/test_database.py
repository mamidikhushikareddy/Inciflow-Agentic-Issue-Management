from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from inciflow.persistence import database


def test_get_engine_uses_expected_configuration():
    fake_settings = MagicMock()
    fake_settings.database_url = "postgresql://test"

    with (
        patch.object(database, "create_engine") as create_engine,
        patch.object(database, "settings", fake_settings),
    ):
        engine = database.get_engine.__wrapped__()

    create_engine.assert_called_once_with(
        "postgresql://test",
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=10,
        connect_args={"connect_timeout": 5},
    )
    assert engine is create_engine.return_value


def test_get_session_factory_uses_shared_engine():
    engine = MagicMock()

    with (
        patch.object(database, "get_engine", return_value=engine) as get_engine,
        patch.object(database, "sessionmaker") as sessionmaker,
    ):
        factory = database.get_session_factory.__wrapped__()

    get_engine.assert_called_once_with()
    sessionmaker.assert_called_once_with(
        bind=engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )
    assert factory is sessionmaker.return_value


def test_get_db_session_yields_session_and_closes_it():
    session = MagicMock()
    factory = MagicMock(return_value=session)

    with patch.object(database, "get_session_factory", return_value=factory):
        generator = database.get_db_session()
        yielded_session = next(generator)

        assert yielded_session is session
        session.close.assert_not_called()

        with pytest.raises(StopIteration):
            next(generator)

    session.close.assert_called_once_with()


def test_get_db_session_closes_session_when_consumer_raises():
    session = MagicMock()
    factory = MagicMock(return_value=session)

    with patch.object(database, "get_session_factory", return_value=factory):
        generator = database.get_db_session()
        assert next(generator) is session

        with pytest.raises(RuntimeError, match="consumer failed"):
            generator.throw(RuntimeError("consumer failed"))

    session.close.assert_called_once_with()
