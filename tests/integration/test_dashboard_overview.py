"""Dashboard overview aggregate endpoint tests (`/api/v1/dashboard/overview`).

Integration: requires local PostgreSQL (docker-compose) via conftest fixtures.
Verifies the Overview fan-out (sites + per-site stats) collapses into one call.
"""

import uuid
from datetime import datetime

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.dependencies import get_current_user
from apps.api.main import app
from apps.api.models.enrichment import EnrichmentProfile
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.models.visitor import IdentifiedVisitor, Visitor

pytestmark = pytest.mark.integration

# Fields VisitorStatsResponse exposes — what /overview must match /stats on.
_STAT_FIELDS = (
    "total_visitors",
    "identified",
    "enriched",
    "could_enrich_more",
    "enriched_unsegmented",
    "eligible_for_resolution",
    "identify_used_today",
    "identify_daily_limit",
    "identify_is_byok",
)


def _visitor(site_id: str, visitor_id: str, **overrides) -> Visitor:
    now = datetime.utcnow()  # visitor timestamps are naive UTC
    defaults = dict(
        site_id=site_id,
        visitor_id=visitor_id,
        first_seen=now,
        last_seen=now,
        intent_score=0.0,
        identity_status="anonymous",
        enrichment_status="pending",
    )
    defaults.update(overrides)
    return Visitor(**defaults)


@pytest_asyncio.fixture
async def user_client(test_client: AsyncClient, test_engine) -> AsyncClient:
    """test_client plus a persisted user that owns one site with one visitor."""
    user_id = uuid.uuid4()
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        s.add(User(id=user_id, email="op@getbeam.fyi"))
        s.add(Site(site_id="site_test1", user_id=user_id, name="Test", url="https://t.co"))
        now = datetime.utcnow()  # visitors timestamps are naive UTC
        s.add(
            Visitor(
                site_id="site_test1",
                visitor_id="v_test1",
                first_seen=now,
                last_seen=now,
                identity_status="identified",
            )
        )
        await s.commit()
    app.dependency_overrides[get_current_user] = lambda: User(id=user_id, email="op@getbeam.fyi")
    yield test_client
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_overview_returns_sites_and_stats(user_client: AsyncClient) -> None:
    resp = await user_client.get("/api/v1/dashboard/overview")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Site list returned, and a stats entry keyed by site_id (the N+1 collapsed).
    assert [s["site_id"] for s in data["sites"]] == ["site_test1"]
    assert "site_test1" in data["stats"]

    stats = data["stats"]["site_test1"]
    assert stats["total_visitors"] == 1
    assert stats["identified"] == 1
    # Full VisitorStatsResponse shape (frontend reuses it directly).
    assert "identify_daily_limit" in stats
    assert "eligible_for_resolution" in stats


@pytest.mark.asyncio
async def test_overview_empty_when_no_sites(test_client: AsyncClient) -> None:
    uid = uuid.uuid4()
    app.dependency_overrides[get_current_user] = lambda: User(id=uid, email="empty@getbeam.fyi")
    try:
        resp = await test_client.get("/api/v1/dashboard/overview")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["sites"] == []
        assert body["stats"] == {}
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest_asyncio.fixture
async def multi_site_client(test_client: AsyncClient, test_engine) -> AsyncClient:
    """A user owning THREE sites with a spread of visitor/enrichment/identify
    state — exercises the batched GROUP BY path (N>1) and the empty-site case."""
    user_id = uuid.uuid4()
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        s.add(User(id=user_id, email="multi@getbeam.fyi"))
        s.add(Site(site_id="site_a", user_id=user_id, name="A", url="https://a.co"))
        s.add(Site(site_id="site_b", user_id=user_id, name="B", url="https://b.co"))
        # site_c has NO visitors — must still return all-zero stats.
        s.add(Site(site_id="site_c", user_id=user_id, name="C", url="https://c.co"))

        # site_a: identified+enriched (segmented), identified+enriched (unsegmented),
        # one anonymous eligible. One low-completeness enrichment
        # profile (could_enrich_more) + one identification today (used quota).
        s.add(_visitor("site_a", "a1", identity_status="identified", enrichment_status="enriched", segmented=True, intent_score=90))
        s.add(_visitor("site_a", "a2", identity_status="identified", enrichment_status="enriched", segmented=False, intent_score=80))
        s.add(_visitor("site_a", "a3", identity_status="anonymous", intent_score=55))
        s.add(EnrichmentProfile(site_id="site_a", visitor_id="a1", enrichment_completeness=0.4))
        s.add(EnrichmentProfile(site_id="site_a", visitor_id="a2", enrichment_completeness=0.9))
        s.add(IdentifiedVisitor(site_id="site_a", visitor_id="a1", resolved_at=datetime.utcnow()))

        # site_b: no identified visitors ever -> inside the first-win boost
        # window, so the intent floor is waived and BOTH anonymous rows count.
        s.add(_visitor("site_b", "b1", identity_status="anonymous", intent_score=40))
        s.add(_visitor("site_b", "b2", identity_status="anonymous", intent_score=10))
        await s.commit()

    app.dependency_overrides[get_current_user] = lambda: User(id=user_id, email="multi@getbeam.fyi")
    yield test_client
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_overview_matches_per_site_stats(multi_site_client: AsyncClient) -> None:
    """The invariant: /overview's per-site numbers must equal the dedicated
    /visitors/{site}/stats endpoint exactly. The two now share NO code, so a
    match cross-checks the batched query against the per-site path."""
    ov = await multi_site_client.get("/api/v1/dashboard/overview")
    assert ov.status_code == 200, ov.text
    overview = ov.json()

    assert {s["site_id"] for s in overview["sites"]} == {"site_a", "site_b", "site_c"}

    for site_id in ("site_a", "site_b", "site_c"):
        single = await multi_site_client.get(f"/api/v1/visitors/{site_id}/stats")
        assert single.status_code == 200, single.text
        per_site = single.json()
        agg = overview["stats"][site_id]
        for field in _STAT_FIELDS:
            assert agg[field] == per_site[field], (
                f"{site_id}.{field}: overview={agg[field]} per-site={per_site[field]}"
            )

    # Pin a few concrete numbers so a both-wrong-identically regression is caught.
    a = overview["stats"]["site_a"]
    assert a["total_visitors"] == 3
    assert a["identified"] == 2
    assert a["enriched"] == 2
    assert a["enriched_unsegmented"] == 1   # a2 only (a1 segmented)
    # site_a has 1 IdentifiedVisitor (< first_win_boost_count=5), so it is also
    # inside the boost window — a3 is its only anonymous row either way.
    assert a["eligible_for_resolution"] == 1  # a3 (the only anonymous row)
    assert a["could_enrich_more"] == 1      # the 0.4 profile only
    assert a["identify_used_today"] == 1    # a1 resolved today
    assert a["identify_daily_limit"] == 50  # free-tier default budget
    assert a["identify_is_byok"] is False

    # site_b: 0 identified ever -> boost active -> floor waived -> b1 AND b2.
    assert overview["stats"]["site_b"]["eligible_for_resolution"] == 2  # b1, b2
    assert overview["stats"]["site_c"]["total_visitors"] == 0  # empty site → zeros
