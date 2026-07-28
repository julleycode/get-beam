"""Ensure the local demo user exists (idempotent).

Used by scripts/dev-local.* so JWT login works without a full seed dump.
Demo credentials: demo@getbeam.fyi / password123
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

# Import the FastAPI app module so every ORM model is registered on Base.metadata
# (same pattern as alembic env.py). Avoids relationship mapper configure errors.
import apps.api.main  # noqa: F401

from apps.api.models.database import async_session
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.services.auth import hash_password

DEMO_EMAIL = "demo@getbeam.fyi"
DEMO_PASSWORD = "password123"
DEMO_SITE_ID = "site_demo123456"


async def ensure() -> None:
    async with async_session() as db:
        result = await db.execute(select(User).where(User.email == DEMO_EMAIL))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                email=DEMO_EMAIL,
                hashed_password=hash_password(DEMO_PASSWORD),
                full_name="Demo User",
            )
            db.add(user)
            await db.flush()
            print(f"Created demo user: {DEMO_EMAIL} / {DEMO_PASSWORD}")
        else:
            user.hashed_password = hash_password(DEMO_PASSWORD)
            print(f"Demo user already exists (password reset): {DEMO_EMAIL}")

        site_result = await db.execute(select(Site).where(Site.site_id == DEMO_SITE_ID))
        site = site_result.scalar_one_or_none()
        if site is None:
            db.add(
                Site(
                    site_id=DEMO_SITE_ID,
                    user_id=user.id,
                    name="Demo SaaS App",
                    url="https://demo.example.com",
                    description="Local demo site",
                    category="SaaS",
                )
            )
            print(f"Created demo site: {DEMO_SITE_ID}")
        else:
            print(f"Demo site already exists: {DEMO_SITE_ID}")

        await db.commit()
        print("OK — local JWT login ready at http://localhost:3000/login")


if __name__ == "__main__":
    try:
        asyncio.run(ensure())
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
