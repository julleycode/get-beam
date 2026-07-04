"""Backfill users.avatar_url (+ empty full_name) from the Clerk Backend API.

New logins capture the Clerk profile image at JIT user creation
(apps/api/dependencies.py); this one-shot script covers accounts created
before the avatar_url column existed so they show real photos on the
landing founders wall.

Only stores images Clerk marks has_image=true (their generated gray
fallback is skipped — the wall's initials tiles look better). Never
overwrites an existing avatar_url unless --force.

USAGE
-----
    python -m scripts.backfill_clerk_avatars              # dry-run: print plan
    python -m scripts.backfill_clerk_avatars --apply      # write changes
    python -m scripts.backfill_clerk_avatars --apply --force  # also overwrite

Run from repo root so `apps.api.*` imports resolve. Uses settings.database_url
and settings.clerk_secret_key (root .env -> prod by default).
"""

import argparse
import asyncio

import httpx
from sqlalchemy import func, select

import apps.api.main  # noqa: F401 — registers every ORM model (User has relationships)
from apps.api.config import settings
from apps.api.models.database import async_session
from apps.api.models.user import User

CLERK_PAGE_SIZE = 100


async def fetch_all_clerk_users() -> list[dict]:
    """Page through GET /v1/users until Clerk returns an empty page."""
    users: list[dict] = []
    offset = 0
    async with httpx.AsyncClient(timeout=15.0) as client:
        while True:
            resp = await client.get(
                "https://api.clerk.com/v1/users",
                params={"limit": CLERK_PAGE_SIZE, "offset": offset},
                headers={"Authorization": f"Bearer {settings.clerk_secret_key}"},
            )
            resp.raise_for_status()
            page = resp.json()
            if not page:
                break
            users.extend(page)
            if len(page) < CLERK_PAGE_SIZE:
                break
            offset += CLERK_PAGE_SIZE
    return users


def primary_email(clerk_user: dict) -> str | None:
    primary_id = clerk_user.get("primary_email_address_id")
    emails = clerk_user.get("email_addresses", []) or []
    for entry in emails:
        if entry.get("id") == primary_id and entry.get("email_address"):
            return entry["email_address"]
    for entry in emails:
        if entry.get("email_address"):
            return entry["email_address"]
    return None


async def run(apply: bool, force: bool) -> None:
    if not settings.clerk_secret_key:
        raise SystemExit("CLERK_SECRET_KEY missing — aborting")

    clerk_users = await fetch_all_clerk_users()
    print(f"clerk users fetched: {len(clerk_users)}")

    updated = 0
    skipped = 0
    unmatched = 0
    async with async_session() as db:
        for cu in clerk_users:
            clerk_id = cu.get("id")
            email = primary_email(cu)
            name = " ".join(
                p for p in [cu.get("first_name"), cu.get("last_name")] if p
            ).strip() or None
            avatar = (
                cu["image_url"] if cu.get("has_image") and cu.get("image_url") else None
            )

            user = None
            if clerk_id:
                result = await db.execute(
                    select(User).where(User.clerk_user_id == clerk_id)
                )
                user = result.scalar_one_or_none()
            if user is None and email:
                result = await db.execute(
                    select(User).where(func.lower(User.email) == email.lower())
                )
                user = result.scalar_one_or_none()
            if user is None:
                unmatched += 1
                print(f"  no local row for clerk {clerk_id} ({email})")
                continue

            changes = []
            if avatar and (force or not user.avatar_url):
                changes.append(f"avatar_url -> {avatar[:60]}...")
                if apply:
                    user.avatar_url = avatar
            if name and not user.full_name:
                changes.append(f"full_name -> {name}")
                if apply:
                    user.full_name = name

            if changes:
                updated += 1
                print(f"  {user.email}: " + "; ".join(changes))
            else:
                skipped += 1

        if apply:
            await db.commit()

    mode = "APPLIED" if apply else "DRY-RUN (use --apply to write)"
    print(f"{mode}: {updated} updated, {skipped} unchanged, {unmatched} unmatched")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write changes")
    parser.add_argument(
        "--force", action="store_true", help="overwrite existing avatar_url"
    )
    args = parser.parse_args()
    asyncio.run(run(apply=args.apply, force=args.force))


if __name__ == "__main__":
    main()
