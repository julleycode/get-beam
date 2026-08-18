"""Alembic migration environment (async).

The target metadata is the app's SQLAlchemy ``Base.metadata``. To make sure
EVERY table is registered (so autogenerate never misses one and proposes a
spurious DROP), we import ``apps.api.main``, which transitively imports all
routers and therefore all models — the same trick tests/conftest.py uses.

The database URL and Supabase pooler connect args are pulled from app settings
so this stays in lockstep with apps/api/models/database.py.
"""

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

# Make the top-level `apps` package importable no matter the CWD.
# env.py lives at apps/api/migrations/env.py -> parents[3] is the repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.api.alembic_dsn_guard import assert_safe_alembic_dsn  # noqa: E402
from apps.api.config import settings  # noqa: E402
from apps.api.models.database import Base  # noqa: E402
import apps.api.main  # noqa: E402,F401  — registers every model on Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _connect_args() -> dict:
    # Supabase pooler doesn't support prepared statements — mirror
    # apps/api/models/database.py so migrations connect the same way.
    if "supabase" in settings.database_url:
        return {"prepared_statement_cache_size": 0, "statement_cache_size": 0}
    return {}


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a DB connection."""
    assert_safe_alembic_dsn(settings.app_env, settings.database_url)
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    assert_safe_alembic_dsn(settings.app_env, settings.database_url)
    connectable = create_async_engine(
        settings.database_url,
        poolclass=pool.NullPool,
        connect_args=_connect_args(),
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
