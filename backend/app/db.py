"""Database engine, session factory and the FastAPI session dependency.

This is the only module that knows how to reach the database. Routes get a
session through :func:`get_db` rather than building engines themselves, so
the connection settings live in exactly one place.

Sessions are **synchronous** on purpose. The routes that touch the database
(``/api/submissions/run``, the history endpoints) are declared with plain
``def``, so FastAPI already runs them in a worker thread - see
``routes/submissions.py``. Mixing an async session into those handlers would
add ceremony without buying anything.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app import config

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Declarative base for every ORM model.

    Models live in :mod:`app.models` and are imported by ``app.models``'
    package ``__init__``, which is what registers them on this metadata.
    Alembic's ``env.py`` imports the package for exactly that reason.
    """


# ``create_engine`` does not open a connection - it only parses the URL and
# builds a pool. That matters: the API must still boot, and ``/api/health``
# must still answer, when Postgres is down or not yet configured.
engine = create_engine(
    config.DATABASE_URL,
    echo=config.DB_ECHO,
    pool_size=config.DB_POOL_SIZE,
    # Validate a pooled connection before handing it out. Without this, a
    # Postgres restart leaves dead connections in the pool and the next
    # request fails with a confusing OperationalError instead of reconnecting.
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    # Keep attributes readable after commit so route code can read
    # ``submission.id`` once the transaction has closed.
    expire_on_commit=False,
)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a session, always closed afterwards."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def check_database() -> tuple[bool, str | None]:
    """Ping the database. Returns ``(ok, error_message)``.

    Used by ``/api/health`` so a misconfigured ``DATABASE_URL`` shows up as a
    readable status instead of a stack trace on the first real request.
    """
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - the message is the whole point
        return False, f"{exc.__class__.__name__}: {exc}"
    return True, None
