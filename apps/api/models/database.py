from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from apps.api.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.app_env == "development",
    # Supabase pooler (transaction mode) doesn't support prepared statements
    connect_args={"prepared_statement_cache_size": 0, "statement_cache_size": 0}
    if "supabase" in settings.database_url
    else {},
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
