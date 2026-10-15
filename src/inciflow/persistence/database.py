"""SQLAlchemy engine and session factory."""

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from inciflow.core.config import settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Create the application database engine once per process."""
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=10,
        connect_args={"connect_timeout": 5},
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Return the shared session factory."""
    return sessionmaker(
        bind=get_engine(),
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )


def get_db_session() -> Generator[Session]:
    """Yield a database session and always close it."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
