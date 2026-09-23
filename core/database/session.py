"""
Module: session.py
Description: Database session management for PROJECT TITAN-X.
Author: Shantanu Waykar
Version: 1.0.0
Last Modified: 2026-06-28
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from project_titan_x.core.config import get_settings
from project_titan_x.core.database.models import Base

_settings = get_settings()
engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    # Every DB write on this platform (risk-event logging, trade journal)
    # is already wrapped in a best-effort try/except that treats a DB
    # failure as non-fatal -- but without an explicit connect_timeout,
    # psycopg2 falls back to the OS-level TCP timeout when Postgres is
    # unreachable (e.g. Docker not started), measured at ~4s PER ATTEMPT
    # on this machine. Since a signal-generation scan can trigger dozens
    # of these calls (one per asset that reaches risk evaluation), an
    # unreachable DB was silently adding minutes to a full watchlist
    # scan -- a "best-effort, non-blocking" fallback that in practice
    # blocked for a very long time. 2s is generous for a healthy local
    # Postgres (which responds in milliseconds) and fails fast otherwise.
    connect_args={"connect_timeout": 2},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Create all database tables."""
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_db_session() -> Generator[Session, Any, None]:
    """
    Provide a transactional database session scope.

    Yields:
        Session: SQLAlchemy session.

    Raises:
        Exception: Re-raises any database error after rollback.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
