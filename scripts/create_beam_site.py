"""One-off: create the beam site record so the tracker can ingest events."""
import asyncio
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from apps.api.config import settings


BEAM_SITE_ID = "beam_getbeam_fyi"
BEAM_URL = "https://getbeam.fyi"


async def main() -> None:
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # Check if site already exists
        result = await db.execute(
            text("SELECT site_id FROM sites WHERE site_id = :sid"),
            {"sid": BEAM_SITE_ID},
        )
        if result.first():
            print(f"Site '{BEAM_SITE_ID}' already exists. Done.")
            return

        # Find owner user
        result = await db.execute(
            text("SELECT id, email FROM users WHERE email IN (:e1, :e2) ORDER BY created_at LIMIT 1"),
            {"e1": "tranthai.work@gmail.com", "e2": "demo@getbeam.fyi"},
        )
        user = result.first()
        if not user:
            print("No user found. Create a user first.")
            return

        site_uuid = str(uuid.uuid4())
        await db.execute(
            text("""
                INSERT INTO sites (id, site_id, user_id, name, url, description, category, pixel_verified, daily_resolution_budget)
                VALUES (:id, :site_id, :user_id, :name, :url, :desc, :cat, false, 50)
            """),
            {
                "id": site_uuid,
                "site_id": BEAM_SITE_ID,
                "user_id": str(user.id),
                "name": "beam landing (getbeam.fyi)",
                "url": BEAM_URL,
                "desc": "Beam marketing site — self-tracking for testing",
                "cat": "Marketing",
            },
        )
        await db.commit()
        print(f"Created site '{BEAM_SITE_ID}' for user {user.email} (id={user.id})")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
