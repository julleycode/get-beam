"""Lane-scoped fixtures for the disposable-container coop e2e lane.

WHY THIS LANE EXISTS
--------------------
``tests/conftest.py`` builds its schema with ``Base.metadata.create_all`` and
never runs alembic, so the MODEL is the schema under test and the migrations are
validated by nothing. And ``httpx.ASGITransport`` never runs the ASGI lifespan,
so ``start_scheduler()`` / ``_coop_expiry_sweep_job`` are executed by no test at
any tier. This lane fixes both against a THROWAWAY container.

The root ``tests/conftest.py`` is deliberately ZERO-DIFF: the whole alembic build
lives here, session-scoped, in ``disposable_schema``.

SAFETY
------
``_dsn_guard`` is session-scoped + autouse AND is an explicit dependency of every
fixture that touches the DB, so it fires before any destructive statement. It
hard-fails on any DSN that is not localhost, or whose port is one of
{5432, 5433, 6543} — the natively-installed Postgres, the shared local dev DB,
and the Supabase pooler respectively.
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[2]
BANNED_PORTS = {5432, 5433, 6543}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

# Coop-relevant tables cleared between tests. The schema itself is built ONCE per
# session (a 60+ revision chain per test would be prohibitively slow — and
# migrations/env.py wraps the whole chain in a single transaction).
_COOP_TABLES = (
    "identity_credit_ledger",
    "identity_contribution_events",
    "identity_contribution_consent_acceptances",
    "sites",
    "visitors",
)


def _parse_dsn(dsn: str) -> tuple[str, int]:
    """Return (host, port). Raises on anything unparseable — fail CLOSED."""
    parts = urlsplit(dsn)
    if not parts.hostname:
        raise ValueError(f"unparseable DSN host in {dsn!r}")
    if parts.port is None:
        raise ValueError(f"unparseable DSN port in {dsn!r}")
    return parts.hostname, parts.port


def assert_disposable_dsn(dsn: str) -> str:
    """Hard-fail unless the DSN is a localhost, non-shared, non-pooler target."""
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL is not set. Run this lane via scripts/e2e-disposable.sh; "
            "falling through to tests/conftest.py's setdefault would target the "
            "SHARED dev DB on :5433 (or, with the repo dotenv, Supabase PROD)."
        )
    try:
        host, port = _parse_dsn(dsn)
    except ValueError as exc:
        raise RuntimeError(f"REFUSING disposable lane: {exc}") from exc
    if host not in LOCAL_HOSTS:
        raise RuntimeError(
            f"REFUSING disposable lane: host {host!r} is not localhost. "
            "This lane DROPs and rebuilds the whole public schema."
        )
    if port in BANNED_PORTS:
        raise RuntimeError(
            f"REFUSING disposable lane: port {port} is reserved "
            f"({sorted(BANNED_PORTS)} = native PG / shared dev DB / Supabase pooler). "
            "Use a disposable container on an ephemeral port."
        )
    return dsn


@pytest.fixture(scope="session", autouse=True)
def _dsn_guard() -> str:
    """DE-21. Fires before any DROP SCHEMA / upgrade head. Fail-closed."""
    return assert_disposable_dsn(os.environ.get("DATABASE_URL", ""))


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess:
    """Run alembic with DATABASE_URL PINNED inline. Never inherit the repo dotenv."""
    env = dict(os.environ)
    env["DATABASE_URL"] = dsn
    env["APP_ENV"] = "test"
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "apps/api/alembic.ini", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def alembic_or_raise(dsn: str, *args: str) -> str:
    proc = _alembic(dsn, *args)
    if proc.returncode != 0:
        raise RuntimeError(
            f"alembic {' '.join(args)} failed (rc={proc.returncode})\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc.stdout


def live_head(dsn: str) -> str:
    """Re-derive the head from `alembic heads` — NEVER trust a written-down hash."""
    out = alembic_or_raise(dsn, "heads")
    heads = [ln.split()[0] for ln in out.splitlines() if ln.strip()]
    if len(heads) != 1:
        raise RuntimeError(f"expected exactly one alembic head, got: {heads!r}")
    return heads[0]


async def _reset_public_schema(dsn: str) -> None:
    """DROP SCHEMA public CASCADE; CREATE SCHEMA public.

    MANDATORY form (C-12/F-3). The weaker `DROP TABLE alembic_version` +
    `Base.metadata.drop_all` leaves behind (a) `alembic_version` itself, which is
    alembic's own DDL and appears NOWHERE in Base.metadata — so the next
    `upgrade head` applies ZERO revisions against an empty schema and every
    subsequent test runs with no tables (the "empty-but-stamped, silently
    no-ops" shape); and (b) any table a migration creates but the ORM never
    declares, which then breaks `upgrade head` on an existing object.

    Verified safe: `grep -rn "CREATE EXTENSION" apps/api/migrations/versions/`
    returns zero matches, so no extension is dropped.
    """
    engine = create_async_engine(dsn, isolation_level="AUTOCOMMIT", poolclass=None)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()


def build_schema(dsn: str) -> str:
    """DROP SCHEMA -> alembic upgrade head. Returns the live head revision."""
    assert_disposable_dsn(dsn)
    asyncio.run(_reset_public_schema(dsn))
    alembic_or_raise(dsn, "upgrade", "head")
    return live_head(dsn)


@pytest.fixture(scope="session")
def disposable_dsn(_dsn_guard: str) -> str:
    return _dsn_guard


@pytest.fixture(scope="session")
def disposable_schema(disposable_dsn: str) -> str:
    """Session-scoped alembic build. Returns the head revision."""
    return build_schema(disposable_dsn)


@pytest_asyncio.fixture
async def disposable_engine(_dsn_guard: str, disposable_schema: str):
    """Prod-parity engine: pool_size=3, max_overflow=2 (models/database.py:70-71).

    FUNCTION-scoped on purpose. pytest-asyncio's default loop scope is `function`,
    so a session-scoped async engine would hand a later test a pooled asyncpg
    connection bound to a DEAD event loop. The SCHEMA is session-scoped (see
    `disposable_schema`); only the engine is per-test.

    Depends on `_dsn_guard` EXPLICITLY (C-15) rather than resting on pytest's
    implicit autouse ordering.
    """
    engine = create_async_engine(
        _dsn_guard, echo=False, pool_size=3, max_overflow=2, pool_pre_ping=False
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def clean_coop(disposable_engine):
    """TRUNCATE the coop-relevant tables before each test (schema is session-built)."""
    async with disposable_engine.begin() as conn:
        await conn.execute(
            text(f"TRUNCATE {', '.join(_COOP_TABLES)} RESTART IDENTITY CASCADE")
        )
    return True


@pytest_asyncio.fixture
async def disposable_db(disposable_engine, clean_coop) -> AsyncSession:
    factory = async_sessionmaker(
        disposable_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session


_SEED_LOT_SQL = text(
    """
    INSERT INTO identity_credit_ledger
        (id, site_id, entry_type, amount, reason, lot_id, spendable_at, expires_at)
    VALUES (:id, :site_id, 'ACCRUE', :amount, 'contribution', :id, :spendable_at, :expires_at)
    """
)


async def seed_lapsed_lot(conn, site_id: str, *, expires_at, spendable_at, amount=1):
    """Insert ONE already-lapsed ACCRUE lot (its own lot_id). Returns the lot id."""
    import uuid as _uuid

    lot = _uuid.uuid4()
    await conn.execute(
        _SEED_LOT_SQL,
        {
            "id": lot,
            "site_id": site_id,
            "amount": amount,
            "spendable_at": spendable_at,
            "expires_at": expires_at,
        },
    )
    return lot


async def seed_site(session, site_id: str, *, contribution_enabled: bool = True):
    """Create a User + Site through the ORM and COMMIT. Returns the User.

    Deliberately ORM, not raw SQL: several `sites`/`users` columns are NOT NULL
    with a PYTHON-side default only (e.g. `sites.pixel_verified`,
    `users.tone_preference`), so a raw INSERT drifts the moment a column is added.
    """
    import uuid as _uuid

    import apps.api.main  # noqa: F401 — registers EVERY model, or User's
    # `SocialAccount` relationship fails to resolve (repo-wide ORM gotcha).
    from apps.api.models.site import Site
    from apps.api.models.user import User

    user = User(id=_uuid.uuid4(), email=f"{site_id}-{_uuid.uuid4().hex[:8]}@example.test")
    session.add(user)
    await session.flush()
    session.add(
        Site(
            site_id=site_id,
            user_id=user.id,
            name=site_id,
            url=f"https://{site_id}.test",
            contribution_enabled=contribution_enabled,
        )
    )
    await session.commit()
    return user


async def expire_row_count(conn, lot_id) -> int:
    res = await conn.execute(
        text(
            "SELECT count(*) FROM identity_credit_ledger "
            "WHERE lot_id = :l AND entry_type = 'EXPIRE'"
        ),
        {"l": lot_id},
    )
    return int(res.scalar() or 0)


@pytest_asyncio.fixture
async def coop_on(monkeypatch):
    """Global co-op flag ON for one test. Same pattern as the integration lane's
    `coop_on` — the flag is read at CALL time and RUN time, never at import, so
    monkeypatching the settings attribute is correct and an env var is not."""
    from apps.api.config import settings

    monkeypatch.setattr(settings, "identity_coop_enabled", True)
    return True


@pytest_asyncio.fixture
async def no_mx(monkeypatch):
    """Deterministic email validation — the real one does a LIVE MX lookup."""
    from apps.api.services import email_validator

    async def _ok(email: str):
        return True, ""

    monkeypatch.setattr(email_validator, "validate_email", _ok)
    return True
