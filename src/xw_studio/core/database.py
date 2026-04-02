"""PostgreSQL / SQLAlchemy session factory (Phase 5)."""
from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from xw_studio.core.config import AppConfig


def create_engine_from_config(config: AppConfig) -> Engine:
    """Create a SQLAlchemy engine from ``DATABASE_URL``."""
    if not (config.database_url or "").strip():
        raise ValueError("DATABASE_URL is not set")
    return create_engine(config.database_url, pool_pre_ping=True, future=True)


def create_session_factory(config: AppConfig) -> sessionmaker[Session]:
    """Return a session factory bound to a new engine."""
    engine = create_engine_from_config(config)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    """Provide a transactional scope around a series of operations."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
