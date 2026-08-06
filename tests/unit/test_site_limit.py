"""Unit tests for per-plan website (Site) count limit enforcement.

Covers:
- get_site_limit() values vs the pricing page (AC4) + unknown-key fallback
- drift guard: PLAN_SITE_LIMITS keys are a subset of PLAN_LIMITS keys
- create_site router behavior with a stubbed AsyncSession (AC1, AC2, AC3, AC5, AC6):
  under limit creates, at limit 402, dedup bypasses, unlimited never counts,
  grandfathered over-limit blocked, lapsed paid plan resolves to free.

All DB interaction is mocked — no live DB, unit lane only.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

import apps.api.main  # noqa: F401  — registers every ORM mapper (same trick as migrations/env.py)
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.routers.sites import create_site
from apps.api.schemas.sites import SiteCreate
from apps.api.services.billing import (
    PLAN_LIMITS,
    PLAN_SITE_LIMITS,
    get_site_limit,
)

pytestmark = pytest.mark.unit


# ──────────────────────────── helpers ────────────────────────────


def _user(plan: str = "free", current_period_end=None) -> User:
    u = User(id=uuid.uuid4(), email="a@b.co", plan=plan)
    u.current_period_end = current_period_end
    return u


def _existing_site(user_id) -> Site:
    """A fully-populated Site so SiteOut.model_validate() succeeds."""
    return Site(
        id=uuid.uuid4(),
        site_id="site_deadbeef1234",
        user_id=user_id,
        name="Existing",
        url="https://example.com",
        description=None,
        category=None,
        detected_platform=None,
        pixel_verified=False,
        daily_resolution_budget=50,
        auto_identify_enabled=True,
        hot_alert_enabled=False,
        tracking_enabled=True,
        consent_mode="off",
        created_at=datetime.now(timezone.utc),
    )


def _fake_db(existing: Site | None = None, count: int = 0) -> Mock:
    """Stub AsyncSession for create_site.

    execute() returns a result whose scalars().first() yields `existing` (the
    dedup lookups) and whose scalar_one() yields `count` (the limit query).
    Every execute() call is recorded so tests can assert the count query was or
    was not issued.
    """
    db = Mock()
    db.executed = []

    result = Mock()
    result.scalars.return_value.first.return_value = existing
    result.scalar_one.return_value = count

    async def _execute(stmt):
        db.executed.append(stmt)
        return result

    async def _refresh(obj):
        # Emulate the DB-side defaults the ORM would populate post-INSERT.
        obj.id = obj.id or uuid.uuid4()
        obj.created_at = obj.created_at or datetime.now(timezone.utc)
        for attr, default in (
            ("detected_platform", None),
            ("pixel_verified", False),
            ("daily_resolution_budget", 50),
            ("auto_identify_enabled", True),
            ("hot_alert_enabled", False),
            ("tracking_enabled", True),
            ("consent_mode", "off"),
        ):
            if getattr(obj, attr, None) is None:
                setattr(obj, attr, default)

    class _Savepoint:
        """create_site wraps the insert in db.begin_nested() so a site_id reuse
        collision is recoverable. A no-op async CM is enough for these tests."""

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    db.execute = _execute
    db.add = Mock()
    db.commit = AsyncMock()
    db.refresh = _refresh
    db.delete = AsyncMock()
    db.begin_nested = Mock(return_value=_Savepoint())
    return db


def _count_queries(db) -> int:
    """How many of the recorded statements are the count(*) limit query."""
    return sum(1 for stmt in db.executed if "count(" in str(stmt).lower())


_BODY = SiteCreate(name="New", url="https://new-site.com")


# ──────────────────────────── helper-level ────────────────────────────


def test_get_site_limit_matches_pricing_page():
    """free=1, pro=3, max=None — mirrors apps/web/src/app/pricing/page.tsx."""
    assert get_site_limit("free") == 1
    assert get_site_limit("pro") == 3
    assert get_site_limit("max") is None


def test_get_site_limit_unknown_plan_falls_back_to_most_restrictive():
    assert get_site_limit("enterprise") == 1
    assert get_site_limit("") == 1


def test_plan_site_limits_keys_are_subset_of_plan_limits():
    """Drift guard: a renamed/added tier must be reflected in both maps."""
    assert set(PLAN_SITE_LIMITS).issubset(set(PLAN_LIMITS))


# ──────────────────────────── router-level ────────────────────────────


@pytest.mark.asyncio
async def test_create_site_blocked_at_limit_returns_402_site_limit_reached():
    user = _user("free")
    db = _fake_db(existing=None, count=1)

    with pytest.raises(HTTPException) as exc:
        await create_site(_BODY, user=user, db=db)

    assert exc.value.status_code == 402
    detail = exc.value.detail
    assert detail["code"] == "site_limit_reached"
    assert detail["plan"] == "free"
    assert detail["limit"] == 1
    assert detail["current_count"] == 1
    assert detail["upgrade_url"] == "/pricing"
    assert "1 website" in detail["message"]
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_site_under_limit_is_allowed():
    user = _user("pro")
    db = _fake_db(existing=None, count=2)

    out = await create_site(_BODY, user=user, db=db)

    assert out.url == "https://new-site.com"
    db.add.assert_called_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_site_dedup_bypasses_limit():
    """Re-POSTing an owned URL at/over the limit returns the existing site."""
    user = _user("free")
    existing = _existing_site(user.id)
    db = _fake_db(existing=existing, count=99)

    out = await create_site(_BODY, user=user, db=db)

    assert out.site_id == existing.site_id
    assert _count_queries(db) == 0  # never reached the limit check
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_unlimited_plan_never_counts_or_blocks():
    user = _user("max")
    db = _fake_db(existing=None, count=10_000)

    out = await create_site(_BODY, user=user, db=db)

    assert out.name == "New"
    assert _count_queries(db) == 0  # limit is None → no count query issued
    db.add.assert_called_once()


@pytest.mark.asyncio
async def test_grandfathered_over_limit_user_is_blocked_with_true_count():
    """Downgraded user keeps existing sites but cannot create another."""
    user = _user("free")
    db = _fake_db(existing=None, count=3)

    with pytest.raises(HTTPException) as exc:
        await create_site(_BODY, user=user, db=db)

    assert exc.value.status_code == 402
    assert exc.value.detail["current_count"] == 3
    assert exc.value.detail["limit"] == 1
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_lapsed_paid_plan_resolves_to_free_limit():
    """A pro plan past current_period_end is gated at the free limit (AC5)."""
    user = _user("pro", current_period_end=datetime.now(timezone.utc) - timedelta(days=30))
    db = _fake_db(existing=None, count=1)

    with pytest.raises(HTTPException) as exc:
        await create_site(_BODY, user=user, db=db)

    assert exc.value.status_code == 402
    assert exc.value.detail["plan"] == "free"
    assert exc.value.detail["limit"] == 1


@pytest.mark.asyncio
async def test_count_query_is_scoped_to_the_requesting_user():
    """AC6 — the count query filters on Site.user_id."""
    user = _user("free")
    db = _fake_db(existing=None, count=0)

    await create_site(_BODY, user=user, db=db)

    count_stmts = [s for s in db.executed if "count(" in str(s).lower()]
    assert len(count_stmts) == 1
    assert "sites.user_id" in str(count_stmts[0])
