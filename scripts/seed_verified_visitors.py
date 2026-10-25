"""Seed 5 fake VERIFIED (identified, emailable, enriched) visitors — LOCAL DB ONLY.

    DATABASE_URL=postgresql+asyncpg://<user>:<pw>@localhost:5433/<db> \\
        .venv/bin/python -m scripts.seed_verified_visitors [--user-id UUID] [--dry-run] [--unseed]

Safety: this repo's ``.env`` points ``DATABASE_URL`` at production. The script
refuses (exit 2, zero writes) unless the DSN host is local. There is NO remote
override flag — local only, by design.

Idempotent: ids are deterministic (uuid5) and each person is delete-then-insert
inside one transaction, so re-running never duplicates rows.

All people are fictional with ``example.com/.org/.net`` emails. Provider is
``form_capture`` (person-level => ``is_emailable_identity`` is True).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

LOCAL_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1", "host.docker.internal"})
ALLOWED_EMAIL_DOMAINS: frozenset[str] = frozenset({"example.com", "example.org", "example.net"})

SEED_SITE_ID = "beam_seed_verified"
SEED_PROVIDER = "form_capture"
SEED_CONFIDENCE = 0.95
_NS = uuid.NAMESPACE_URL

ROSTER: list[dict[str, str]] = [
    {"slug": "ava-chen", "full_name": "Ava Chen", "email": "ava.chen@example.com",
     "job_title": "Head of Growth", "company_name": "Example Labs", "city": "San Francisco",
     "region": "CA", "country": "US"},
    {"slug": "marco-rossi", "full_name": "Marco Rossi", "email": "marco.rossi@example.org",
     "job_title": "Founder", "company_name": "Rossi Goods", "city": "Milan",
     "region": "Lombardy", "country": "IT"},
    {"slug": "priya-nair", "full_name": "Priya Nair", "email": "priya.nair@example.net",
     "job_title": "VP Marketing", "company_name": "Nair Analytics", "city": "Bengaluru",
     "region": "KA", "country": "IN"},
    {"slug": "lucas-meyer", "full_name": "Lucas Meyer", "email": "lucas.meyer@example.com",
     "job_title": "CTO", "company_name": "Meyer Cloud", "city": "Berlin",
     "region": "BE", "country": "DE"},
    {"slug": "sofia-alves", "full_name": "Sofia Alves", "email": "sofia.alves@example.org",
     "job_title": "Product Lead", "company_name": "Alves Studio", "city": "Lisbon",
     "region": "Lisbon", "country": "PT"},
]


class NonLocalDatabaseError(RuntimeError):
    pass


def is_local_db_url(url: str | None) -> bool:
    """True only when the DSN host is local. Fail-closed on anything unparseable."""
    if not url:
        return False
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return False
    if not host:
        return False
    return host.lower().strip("[]") in LOCAL_HOSTS


def _assert_local_dsn(url: str | None) -> None:
    if not is_local_db_url(url):
        raise NonLocalDatabaseError(
            "Refusing to seed: DATABASE_URL is not a local database. "
            "Pin DATABASE_URL to localhost:5433 inline."
        )


def visitor_id_for(slug: str) -> str:
    return str(uuid.uuid5(_NS, f"seed-verified-{slug}"))


def _validate_roster() -> None:
    for p in ROSTER:
        domain = p["email"].rsplit("@", 1)[1]
        if domain not in ALLOWED_EMAIL_DOMAINS:
            raise ValueError(f"roster email domain not allowed: {p['slug']}")


async def _resolve_owner(db, user_id: str | None) -> uuid.UUID:
    from sqlalchemy import select

    from apps.api.models.user import User

    if user_id:
        owner = uuid.UUID(user_id)
        found = await db.scalar(select(User.id).where(User.id == owner))
        if found is None:
            raise SystemExit(f"--user-id {user_id} not found in local users table")
        return owner
    first = await db.scalar(select(User.id).order_by(User.created_at.asc()).limit(1))
    if first is None:
        raise SystemExit("No local users found — sign up locally first, or pass --user-id")
    return first


async def _run(user_id: str | None, dry_run: bool, unseed: bool) -> int:
    # Imported only after the DSN guard has passed.
    from sqlalchemy import delete, select

    from apps.api.models.database import async_session
    from apps.api.models.enrichment import EnrichmentProfile
    from apps.api.models.site import Site
    from apps.api.models.visitor import IdentifiedVisitor, Visitor
    from apps.api.models.visitor_email import VisitorEmail, normalize_source
    from apps.api.services.pii_crypto import email_hash, encrypt_pii, normalize_email

    ids = [visitor_id_for(p["slug"]) for p in ROSTER]
    if dry_run:
        for p, vid in zip(ROSTER, ids):
            print(f"[dry-run] {SEED_SITE_ID} {vid[:8]} {p['slug']}")
        return 0

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with async_session() as db:
        async with db.begin():
            for model in (EnrichmentProfile, VisitorEmail, IdentifiedVisitor, Visitor):
                await db.execute(
                    delete(model).where(model.site_id == SEED_SITE_ID, model.visitor_id.in_(ids))
                )
            if unseed:
                await db.execute(delete(Site).where(Site.site_id == SEED_SITE_ID))
                print(f"unseeded {len(ids)} visitors + site {SEED_SITE_ID}")
                return 0

            site = await db.scalar(select(Site).where(Site.site_id == SEED_SITE_ID))
            if site is None:
                owner = await _resolve_owner(db, user_id)
                db.add(Site(site_id=SEED_SITE_ID, user_id=owner,
                            name="Beam Seed (verified visitors)", url="https://example.com"))

            for i, (p, vid) in enumerate(zip(ROSTER, ids)):
                email = normalize_email(p["email"])
                bidx = email_hash(email)
                cipher = encrypt_pii(email)
                db.add(Visitor(
                    site_id=SEED_SITE_ID, visitor_id=vid,
                    first_seen=now - timedelta(days=7 + i), last_seen=now - timedelta(hours=i),
                    total_pageviews=6 + i, total_sessions=2 + (i % 3), avg_time_on_page=45.0 + i,
                    max_scroll_depth=70, pages_visited=["/", "/pricing", "/features"],
                    country_code=p["country"], device_type="desktop",
                    intent_score=0.7, identity_status="identified", enrichment_status="enriched",
                ))
                db.add(IdentifiedVisitor(
                    site_id=SEED_SITE_ID, visitor_id=vid, email=email, full_name=p["full_name"],
                    city=p["city"], region=p["region"], country=p["country"],
                    resolution_provider=SEED_PROVIDER, confidence_score=SEED_CONFIDENCE,
                    email_ciphertext=cipher, email_bidx=bidx,
                    full_name_ciphertext=encrypt_pii(p["full_name"]),
                    resolved_at=now, confirmed_at=now,
                ))
                db.add(VisitorEmail(
                    site_id=SEED_SITE_ID, visitor_id=vid, email=email,
                    source=normalize_source("form"), email_ciphertext=cipher, email_bidx=bidx,
                ))
                db.add(EnrichmentProfile(
                    site_id=SEED_SITE_ID, visitor_id=vid,
                    job_title=p["job_title"], company_name=p["company_name"],
                    social_context={}, enrichment_completeness=0.5,
                ))
    print(f"seeded {len(ids)} verified visitors into site {SEED_SITE_ID}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed 5 fake verified visitors (local DB only)")
    parser.add_argument("--user-id", help="owner user UUID (default: first local user)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--unseed", action="store_true")
    args = parser.parse_args(argv)

    try:
        _assert_local_dsn(os.environ.get("DATABASE_URL"))
        from apps.api.config import settings

        _assert_local_dsn(settings.database_url)
    except NonLocalDatabaseError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    _validate_roster()
    return asyncio.run(_run(args.user_id, args.dry_run, args.unseed))


if __name__ == "__main__":
    sys.exit(main())
