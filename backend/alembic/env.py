"""Alembic environment.

Two deliberate departures from the generated default:

1.  **The database URL is read from ``app.config``, not from
    ``alembic.ini``.** That keeps one source of truth: ``DATABASE_URL`` in
    ``backend/.env``. It also sidesteps a real trap - Alembic stores its
    config through ``ConfigParser``, which does ``%``-interpolation, so a
    password containing ``%`` would blow up with an
    ``InterpolationSyntaxError`` if it went through ``set_main_option``.
    Building the engine directly avoids that class of bug entirely.

2.  **``app.models`` is imported for its side effect.** Models register
    themselves on ``Base.metadata`` when imported. A model module that is
    never imported is invisible to autogenerate, and the migration it should
    have produced is silently omitted - which shows up much later as a
    missing column at runtime.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import create_engine, pool

from alembic import context

# Make the `app` package importable when alembic runs from `backend/`.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app import config as app_config  # noqa: E402
from app.db import Base  # noqa: E402
import app.models  # noqa: E402,F401  - registers every table on Base.metadata

alembic_config = context.config

if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting (``alembic upgrade --sql``)."""
    context.configure(
        url=app_config.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect and apply migrations."""
    # NullPool: a migration run is short-lived and must not leave pooled
    # connections behind holding locks on the tables it just altered.
    connectable = create_engine(app_config.DATABASE_URL, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Detect column type changes during autogenerate. Off by default,
            # and the reason a widened column silently produces an empty diff.
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
