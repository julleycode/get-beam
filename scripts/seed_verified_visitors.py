"""Seed 5 fake VERIFIED (identified, enriched) visitors — local by default, remote opt-in.

    DATABASE_URL=postgresql+asyncpg://<user>:<pw>@localhost:5433/<db> \\
        .venv/bin/python -m scripts.seed_verified_visitors [--user-id UUID] [--dry-run] [--unseed]
            [--demo-company]

``--demo-company`` also seeds a 6th placeholder person at a real company
(Stripe) whose profile has NO ``social_context["web"]`` key, so the TinyFish
enrichment step (4c) has something to add during a demo. ``--unseed`` always
removes it too.

Safety: this repo's ``.env`` points ``DATABASE_URL`` at production. By default the
script refuses (exit 2, zero writes) unless the DSN host is local.

Remote (demo) mode is an explicit opt-in and needs ALL of:
  * ``--allow-remote`` AND ``--owner-email EMAIL`` (``--user-id`` is rejected) — else exit 2
  * the owner must match exactly one user, case-insensitive — else exit 3 (never creates users)
  * a per-owner demo site ``beam_seed_verified_<sha256(owner_id)[:10]>``; if it exists
    under another owner — exit 4
  * ``PII_HMAC_KEY`` present AND an effective Fernet-valid PII key
    (``PII_ENCRYPTION_KEY or ENCRYPTION_KEY``, mirroring ``pii_crypto._get_fernet``)
    — else exit 5. Never writes plaintext PII into ``*_ciphertext`` columns.
  * ``--yes`` to write. Without it the script prints a summary (DB hostname only,
    owner id, site id, row counts) and exits 0 with zero writes.
``--unseed`` in remote mode deletes everything scoped to that one demo site (5 child
tables, then the site). Run it with the prod env injected, e.g.:

    railway run --service retarget-agent --environment production -- \\
        /Users/apple/.venvs/get-beam/bin/python -m scripts.seed_verified_visitors \\
        --allow-remote --owner-email you@example.com --demo-company [--yes]

Never-email guard (both modes): every seeded ``IdentifiedVisitor`` has
``do_not_email=True``, new seed sites get ``hot_alert_enabled=False``, and all emails
are RFC 2606 ``example.*`` addresses.

Idempotent: ids are deterministic (uuid5) and each person is delete-then-insert
inside one transaction, so re-running never duplicates rows.

All people are fictional with ``example.com/.org/.net`` emails. Provider is
``form_capture`` (person-level => ``is_emailable_identity`` is True).
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
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
SEED_SITE_NAME = "Beam Demo (fictional visitors)"
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


# Opt-in demo row (--demo-company). Placeholder person, real company, so Step 4c
# web research can find public pages. Person fields are pre-filled; social_context
# deliberately has no "web" key. EnrichmentProfile has no company-domain column.
DEMO_PERSON: dict[str, str] = {
    "slug": "demo-visitor", "full_name": "Demo Visitor", "email": "demo.visitor@example.com",
    "job_title": "Head of Partnerships", "company_name": "Stripe", "city": "San Francisco",
    "region": "CA", "country": "US",
}


def roster_for(demo_company: bool = False) -> list[dict[str, str]]:
    return [*ROSTER, DEMO_PERSON] if demo_company else list(ROSTER)


class NonLocalDatabaseError(RuntimeError):
    pass


class SeedAbort(RuntimeError):
    """Refusal after the DSN guard; ``code`` is the process exit code (3/4/5)."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


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


def db_host(url: str | None) -> str | None:
    """Hostname only (no user/password/port/db). None when unparseable."""
    if not url:
        return None
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    return host or None


def check_target(dsn: str | None, allow_remote: bool, owner_email: str | None,
                 user_id: str | None) -> str:
    """Return ``"local"`` or ``"remote"``; raise NonLocalDatabaseError (exit 2) otherwise."""
    if allow_remote:
        if not owner_email:
            raise NonLocalDatabaseError("--allow-remote requires --owner-email")
        if user_id:
            raise NonLocalDatabaseError("--user-id is not allowed with --allow-remote")
        if not db_host(dsn):
            raise NonLocalDatabaseError("Refusing: DATABASE_URL is missing or unparseable")
        return "remote"
    if owner_email:
        raise NonLocalDatabaseError("--owner-email requires --allow-remote")
    _assert_local_dsn(dsn)
    return "local"


def effective_pii_key_valid(pii_encryption_key: str | None,
                            encryption_key: str | None) -> bool:
    """True when the key ``encrypt_pii`` would use is a valid Fernet key."""
    from cryptography.fernet import Fernet

    key = pii_encryption_key or encryption_key
    if not key:
        return False
    try:
        Fernet(key.encode())
    except Exception:  # malformed key -> encrypt_pii would silently pass plaintext through
        return False
    return True


def remote_site_id(owner_id: uuid.UUID | str) -> str:
    return f"{SEED_SITE_ID}_{hashlib.sha256(str(owner_id).encode()).hexdigest()[:10]}"


def visitor_id_for(slug: str, site_id: str | None = None) -> str:
    """Local ids are unchanged; remote ids are scoped to the demo site."""
    if site_id is None:
        return str(uuid.uuid5(_NS, f"seed-verified-{slug}"))
    return str(uuid.uuid5(_NS, f"seed-verified-{site_id}-{slug}"))


def _validate_roster() -> None:
    for p in roster_for(demo_company=True):
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


def _register_models() -> None:
    """Import every model module so ORM relationships resolve (``User`` references
    e.g. ``SocialAccount`` by name). Called only after the DSN guard."""
    import importlib
    import pkgutil

    import apps.api.models as models_pkg

    for mod in pkgutil.iter_modules(models_pkg.__path__):
        importlib.import_module(f"{models_pkg.__name__}.{mod.name}")


async def _resolve_owner_by_email(db, email: str) -> uuid.UUID:
    """Exact, case-insensitive match. 0 or >1 users -> SeedAbort(3). Never creates."""
    from sqlalchemy import func, select

    from apps.api.models.user import User

    _register_models()
    rows = (await db.execute(
        select(User.id).where(func.lower(User.email) == email.strip().lower()).limit(2)
    )).scalars().all()
    if len(rows) != 1:
        raise SeedAbort(3, f"--owner-email matched {len(rows)} users (need exactly 1)")
    return rows[0]


SEED_TABLES = ("sites", "visitors", "identified_visitors", "visitor_emails", "enrichment_profiles")


def summarize(*, mode: str, host: str | None, owner_id, site_id: str, action: str,
              counts: dict[str, int], will_write: bool) -> str:
    """Operator summary. Hostname only — never the DSN, keys, or emails."""
    lines = [
        f"mode: {mode}",
        f"db host: {host or '?'}",
        f"owner user id: {owner_id}",
        f"site id: {site_id}",
        f"action: {action}",
        *(f"  {t}: {counts.get(t, 0)}" for t in (*SEED_TABLES, "events") if t in counts),
        "writing now (--yes)" if will_write else "DRY RUN — no writes. Re-run with --yes to apply.",
    ]
    return "\n".join(lines)


async def _run_remote(owner_email: str, unseed: bool, demo_company: bool, yes: bool,
                      host: str | None) -> int:
    from sqlalchemy import delete, func, select

    from apps.api.models.database import async_session
    from apps.api.models.enrichment import EnrichmentProfile
    from apps.api.models.event import Event
    from apps.api.models.site import Site
    from apps.api.models.visitor import IdentifiedVisitor, Visitor
    from apps.api.models.visitor_email import VisitorEmail

    _register_models()
    children = (EnrichmentProfile, VisitorEmail, IdentifiedVisitor, Visitor, Event)
    async with async_session() as db:
        async with db.begin():
            owner = await _resolve_owner_by_email(db, owner_email)
            site_id = remote_site_id(owner)
            site = await db.scalar(select(Site).where(Site.site_id == site_id))
            if site is not None and site.user_id != owner:
                raise SeedAbort(4, f"site {site_id} exists under a different owner; refusing")

            if unseed:
                counts = {"sites": 1 if site is not None else 0}
                for model in children:
                    counts[model.__tablename__] = int(await db.scalar(
                        select(func.count()).select_from(model).where(model.site_id == site_id)
                    ) or 0)
                print(summarize(mode="remote", host=host, owner_id=owner, site_id=site_id,
                                action="unseed", counts=counts, will_write=yes))
                if not yes:
                    return 0
                for model in children:
                    await db.execute(delete(model).where(model.site_id == site_id))
                await db.execute(delete(Site).where(Site.site_id == site_id, Site.user_id == owner))
                print(f"unseeded site {site_id}")
                return 0

            n = len(roster_for(demo_company))
            counts = {"sites": 0 if site is not None else 1, "visitors": n,
                      "identified_visitors": n, "visitor_emails": n, "enrichment_profiles": n}
            print(summarize(mode="remote", host=host, owner_id=owner, site_id=site_id,
                            action="seed", counts=counts, will_write=yes))
            if not yes:
                return 0
            await _write_people(db, site_id, owner if site is None else None,
                                demo_company, scoped_ids=True)
    print(f"seeded {n} verified visitors into site {site_id}")
    return 0


async def _write_people(db, site_id: str, new_site_owner, demo_company: bool,
                        scoped_ids: bool) -> int:
    """Delete-then-insert the roster into ``site_id``. Creates the site when
    ``new_site_owner`` is given. Never touches cross-tenant tables."""
    from sqlalchemy import delete

    from apps.api.models.enrichment import EnrichmentProfile
    from apps.api.models.site import Site
    from apps.api.models.visitor import IdentifiedVisitor, Visitor
    from apps.api.models.visitor_email import VisitorEmail, normalize_source
    from apps.api.services.pii_crypto import email_hash, encrypt_pii, normalize_email

    sid = site_id if scoped_ids else None
    people = roster_for(demo_company)
    ids = [visitor_id_for(p["slug"], sid) for p in people]
    # Delete set always includes the demo row: --unseed (and a re-run without the
    # flag) must never leave it behind.
    delete_ids = [visitor_id_for(p["slug"], sid) for p in roster_for(demo_company=True)]
    for model in (EnrichmentProfile, VisitorEmail, IdentifiedVisitor, Visitor):
        await db.execute(
            delete(model).where(model.site_id == site_id, model.visitor_id.in_(delete_ids))
        )
    if new_site_owner is not None:
        db.add(Site(site_id=site_id, user_id=new_site_owner, name=SEED_SITE_NAME,
                    url="https://example.com", hot_alert_enabled=False))

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for i, (p, vid) in enumerate(zip(people, ids)):
        email = normalize_email(p["email"])
        bidx = email_hash(email)
        cipher = encrypt_pii(email)
        db.add(Visitor(
            site_id=site_id, visitor_id=vid,
            first_seen=now - timedelta(days=7 + i), last_seen=now - timedelta(hours=i),
            total_pageviews=6 + i, total_sessions=2 + (i % 3), avg_time_on_page=45.0 + i,
            max_scroll_depth=70, pages_visited=["/", "/pricing", "/features"],
            country_code=p["country"], device_type="desktop",
            intent_score=0.7, identity_status="identified", enrichment_status="enriched",
        ))
        db.add(IdentifiedVisitor(
            site_id=site_id, visitor_id=vid, email=email, full_name=p["full_name"],
            city=p["city"], region=p["region"], country=p["country"],
            resolution_provider=SEED_PROVIDER, confidence_score=SEED_CONFIDENCE,
            email_ciphertext=cipher, email_bidx=bidx,
            full_name_ciphertext=encrypt_pii(p["full_name"]),
            resolved_at=now, confirmed_at=now, do_not_email=True,
        ))
        db.add(VisitorEmail(
            site_id=site_id, visitor_id=vid, email=email,
            source=normalize_source("form"), email_ciphertext=cipher, email_bidx=bidx,
        ))
        db.add(EnrichmentProfile(
            site_id=site_id, visitor_id=vid,
            job_title=p["job_title"], company_name=p["company_name"],
            social_context={}, enrichment_completeness=0.5,
        ))
    return len(ids)


async def _run(user_id: str | None, dry_run: bool, unseed: bool, demo_company: bool = False) -> int:
    # Imported only after the DSN guard has passed.
    from sqlalchemy import select

    from apps.api.models.database import async_session
    from apps.api.models.site import Site

    people = roster_for(demo_company)
    if dry_run:
        for p in people:
            print(f"[dry-run] {SEED_SITE_ID} {visitor_id_for(p['slug'])[:8]} {p['slug']}")
        return 0

    _register_models()
    async with async_session() as db:
        async with db.begin():
            if unseed:
                await _unseed_local(db)
                return 0
            site = await db.scalar(select(Site).where(Site.site_id == SEED_SITE_ID))
            owner = await _resolve_owner(db, user_id) if site is None else None
            n = await _write_people(db, SEED_SITE_ID, owner, demo_company, scoped_ids=False)
    print(f"seeded {n} verified visitors into site {SEED_SITE_ID}")
    return 0


async def _unseed_local(db) -> None:
    from sqlalchemy import delete

    from apps.api.models.enrichment import EnrichmentProfile
    from apps.api.models.site import Site
    from apps.api.models.visitor import IdentifiedVisitor, Visitor
    from apps.api.models.visitor_email import VisitorEmail

    delete_ids = [visitor_id_for(p["slug"]) for p in roster_for(demo_company=True)]
    for model in (EnrichmentProfile, VisitorEmail, IdentifiedVisitor, Visitor):
        await db.execute(
            delete(model).where(model.site_id == SEED_SITE_ID, model.visitor_id.in_(delete_ids))
        )
    await db.execute(delete(Site).where(Site.site_id == SEED_SITE_ID))
    print(f"unseeded {len(delete_ids)} visitors + site {SEED_SITE_ID}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed fake verified visitors (local by default)")
    parser.add_argument("--user-id", help="owner user UUID (local only; default: first local user)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--unseed", action="store_true")
    parser.add_argument("--demo-company", action="store_true",
                        help="also seed a 6th placeholder visitor at Stripe for the TinyFish demo")
    parser.add_argument("--allow-remote", action="store_true",
                        help="permit a non-local DSN (requires --owner-email)")
    parser.add_argument("--owner-email", help="remote mode: exact email of the demo site owner")
    parser.add_argument("--yes", action="store_true", help="remote mode: actually write")
    args = parser.parse_args(argv)

    try:
        mode = check_target(os.environ.get("DATABASE_URL"), args.allow_remote,
                            args.owner_email, args.user_id)
        from apps.api.config import settings

        check_target(settings.database_url, args.allow_remote, args.owner_email, args.user_id)
    except NonLocalDatabaseError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    _validate_roster()
    if mode == "local":
        return asyncio.run(_run(args.user_id, args.dry_run, args.unseed, args.demo_company))

    if not settings.pii_hmac_key:
        print("Refusing: PII_HMAC_KEY missing in env", file=sys.stderr)
        return 5
    if not effective_pii_key_valid(settings.pii_encryption_key, settings.encryption_key):
        print("Refusing: no valid Fernet PII key (PII_ENCRYPTION_KEY or ENCRYPTION_KEY)",
              file=sys.stderr)
        return 5
    try:
        return asyncio.run(_run_remote(args.owner_email, args.unseed, args.demo_company,
                                       args.yes and not args.dry_run,
                                       db_host(settings.database_url)))
    except SeedAbort as exc:
        print(str(exc), file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
