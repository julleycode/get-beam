"""Ensure the local demo user exists (idempotent).

Used by scripts/dev-local.* so JWT login works without a full seed dump.
Demo credentials: demo@getbeam.fyi / password123

The password is overridable via ``BEAM_DEMO_PASSWORD`` because this script
RESETS it on every run. That is harmless while the dashboard is bound to
localhost, and dangerous the moment it is published through a tunnel: hardening
the account by hand in the database would be silently undone by the next
``dev-local`` run, and ``/api/v1/auth/login`` has no rate limit. Set the env var
in the repo ``.env`` whenever the dashboard host is publicly reachable.
"""
from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import select

# Import the FastAPI app module so every ORM model is registered on Base.metadata
# (same pattern as alembic env.py). Avoids relationship mapper configure errors.
import apps.api.main  # noqa: F401

from apps.api.models.database import async_session
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.services.auth import hash_password

def _from_env_file(key: str) -> str | None:
    """Read one key straight out of the repo ``.env``.

    ``os.getenv`` alone is not enough: the API reads ``.env`` through
    pydantic-settings, which never copies those values into ``os.environ``. A
    variable set only in ``.env`` is therefore invisible to this script, and the
    failure is silent — the password quietly falls back to the default and the
    account stays weak on a published host. Real environment variables still
    win, so ``dev-local`` or CI can override without touching the file.
    """
    from pathlib import Path

    for candidate in (
        Path(__file__).resolve().parent.parent / ".env",  # repo root
        Path.cwd() / ".env",
    ):
        try:
            for raw in candidate.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, _, value = line.partition("=")
                if name.strip() == key:
                    return value.strip().strip('"').strip("'") or None
        except OSError:
            continue
    return None


DEMO_EMAIL = os.getenv("BEAM_DEMO_EMAIL") or _from_env_file("BEAM_DEMO_EMAIL") or "demo@getbeam.fyi"
DEMO_PASSWORD = (
    os.getenv("BEAM_DEMO_PASSWORD") or _from_env_file("BEAM_DEMO_PASSWORD") or "password123"
)
DEMO_SITE_ID = "site_demo123456"
# Only echo the password when it is the well-known local default. A custom one
# is a real credential and must not land in a terminal scrollback or CI log.
_SHOWN_PASSWORD = DEMO_PASSWORD if DEMO_PASSWORD == "password123" else "(from BEAM_DEMO_PASSWORD)"


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
            print(f"Created demo user: {DEMO_EMAIL} / {_SHOWN_PASSWORD}")
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
