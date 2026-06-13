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
    pool_size=10,
    max_overflow=20,
    pool_recycle=300,
    pool_pre_ping=True,
    # Supabase pooler doesn't support prepared statements, so disable asyncpg's
    # statement cache. NOTE: DATABASE_URL currently points at the SESSION-mode
    # pooler (port 5432) -- NOT transaction mode (6543), despite what this
    # comment used to claim. These args are required for the pooler either way;
    # changing the pooler mode/pool size is deferred (plan P11, outage risk).
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
