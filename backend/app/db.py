"""SQLite engine and session handling."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from .config import settings

engine: Engine = create_engine(
    settings.db_url,
    # FastAPI handles concurrency in threads; SQLite's default check would
    # surface as spurious "database is locked" errors under parallel reads.
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    from . import models  # noqa: F401  (registers the tables)

    db_path = settings.database_path
    if db_path is not None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Session for use outside a request, such as background jobs."""
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with Session(engine) as session:
        yield session