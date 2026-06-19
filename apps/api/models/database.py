import uuid
from collections.abc import AsyncGenerator
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from apps.api.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.app_env == "development",
    # Supabase SESSION-mode pooler (port 5432) caps total clients at 15. The old
    # pool_size=10/max_overflow=20 (up to 30/container) exceeded that the moment a
    # deploy ran two containers at once -> the new container couldn't connect and
    # the deploy failed (EMAXCONNSESSION). Keep one container's pool small enough
    # that old+new overlap stays under 15: 5 max each -> 10 peak. Plenty for the
    # current low traffic; raise this (or move to the 6543 transaction pooler for
    # real headroom) when concurrency grows.
    pool_size=3,
    max_overflow=2,
    pool_recycle=300,
    pool_pre_ping=True,
    # Supabase pooler doesn't support prepared statements, so disable asyncpg's
    # statement cache. Required for the pooler in either session or transaction mode.
    connect_args={"prepared_statement_cache_size": 0, "statement_cache_size": 0}
    if "supabase" in settings.database_url
    else {},
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
