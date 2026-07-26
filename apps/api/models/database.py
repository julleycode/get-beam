import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from urllib.parse import urlsplit

from sqlalchemy import DateTime, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from apps.api.config import settings


def _db_port(url: str) -> int | None:
    """Port from a SQLAlchemy/asyncpg DSN, or None if absent/unparseable.

    Capacity-hardening 4b: the old branch keyed only on ``"supabase" in url``, so
    it could not tell the SESSION pooler (5432, 15-client cap) from the
    TRANSACTION pooler (6543, much larger cap). The port is the only signal that
    distinguishes them. Never raises — a malformed URL degrades to None, which is
    treated as "unknown pooler mode" and gets the conservative defaults.
    """
    try:
        return urlsplit(url).port
    except ValueError:
        return None


def build_connect_args(url: str, statement_timeout_ms: int) -> dict:
    """asyncpg ``connect_args`` for this DSN.

    Two invariants, both load-bearing:

    1. The Supabase pooler does not support prepared statements, so BOTH
       ``prepared_statement_cache_size`` and ``statement_cache_size`` must be 0 —
       for BOTH pooler modes (5432 and 6543). Dropping either one regresses the
       Supabase pooler fix.
    2. ``statement_timeout`` is applied SERVER-SIDE via ``server_settings`` so
       Postgres kills the backend itself. ``statement_timeout_ms == 0`` omits the
       key entirely, leaving today's exact behavior rather than sending "0".
    """
    args: dict = {}
    if "supabase" in url:
        args["prepared_statement_cache_size"] = 0
        args["statement_cache_size"] = 0
    if statement_timeout_ms > 0:
        args["server_settings"] = {"statement_timeout": str(statement_timeout_ms)}
    return args


DB_PORT = _db_port(settings.database_url)
# 6543 = Supabase TRANSACTION pooler; 5432 = SESSION pooler. Recorded for
# operator visibility and for the pool math in config.py. The port change itself
# is an operator action and is NOT recommended while retention.py holds advisory
# locks across statements (transaction-pooler-advisory-lock-audit NOTE).
DB_POOLER_MODE = (
    "transaction" if DB_PORT == 6543 else "session" if DB_PORT == 5432 else "unknown"
)

engine = create_async_engine(
    settings.database_url,
    echo=settings.app_env == "development",
    # Supabase SESSION-mode pooler (port 5432) caps total clients at 15. The old
    # pool_size=10/max_overflow=20 (up to 30/container) exceeded that the moment a
    # deploy ran two containers at once -> the new container couldn't connect and
    # the deploy failed (EMAXCONNSESSION). Keep one container's pool small enough
    # that old+new overlap stays under 15: 5 max each -> 10 peak.
    # Now config-driven (capacity-hardening 4b); the defaults reproduce the old
    # hardcoded 3/2 exactly under EITHER pooler mode. Raising them is an operator
    # action bounded by the pool math documented in config.py.
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_recycle=300,
    pool_pre_ping=True,
    connect_args=build_connect_args(
        settings.database_url, settings.db_statement_timeout_ms
    ),
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
