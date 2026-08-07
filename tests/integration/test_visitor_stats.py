"""Integration tests for visitor stats + resolution observability fields.

Covers the beta-feedback additions:
- GET /visitors/{site_id}/stats: enriched_unsegmented (segmentation-trigger
  count), eligible_for_resolution, and the daily identify quota trio.
- GET /visitors/{site_id}/{visitor_id}: last_resolution_attempt,
  resolution_providers_tried, resolution_skip_reason.

Requires: PostgreSQL running locally (via docker-compose).
"""

import uuid as uuidlib
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "Stats Tester"},
    )
    if resp.status_code != 200:
        resp = await test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "testpass123"}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _visitor(site_id: str, visitor_id: str, **overrides):
    from apps.api.models.visitor import Visitor

    defaults = dict(
        site_id=site_id,
        visitor_id=visitor_id,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        pages_visited=[],
        ip_address="203.0.113.7",
        intent_score=0.0,
        identity_status="anonymous",
        enrichment_status="pending",
    )
    defaults.update(overrides)
    return Visitor(**defaults)


@pytest_asyncio.fixture
async def stats_setup(test_client, test_db):
    """User (via signup), their site, and a spread of visitors."""
    from apps.api.models.site import Site
    from apps.api.models.user import User

    email = f"stats-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)

    result = await test_db.execute(select(User).where(User.email == email))
    user = result.scalar_one()

    site_id = f"stats_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=site_id, user_id=user.id, name="Stats Site", url="https://stats.example.com"))

    test_db.add(_visitor(site_id, "v-eligible", intent_score=75.0))
    test_db.add(_visitor(site_id, "v-low-intent", intent_score=10.0))
    test_db.add(_visitor(site_id, "v-no-ip", intent_score=55.0, ip_address=None))
    test_db.add(
        _visitor(
            site_id, "v-enriched-new",
            intent_score=80.0, identity_status="identified",
            enrichment_status="enriched", segmented=False,
        )
    )
    test_db.add(
        _visitor(
            site_id, "v-enriched-old",
            intent_score=85.0, identity_status="identified",
            enrichment_status="enriched", segmented=True,
        )
    )
    await test_db.commit()

    return {"token": token, "site_id": site_id, "user": user}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestVisitorStats:
    @pytest.mark.asyncio
    async def test_stats_new_fields(self, test_client, stats_setup):
        resp = await test_client.get(
            f"/api/v1/visitors/{stats_setup['site_id']}/stats",
            headers=_auth(stats_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["total_visitors"] == 5
        # enriched_unsegmented excludes the segmented=True visitor
        assert data["enriched"] == 2
        assert data["enriched_unsegmented"] == 1
        # eligible_for_resolution: the site has 0 identified visitors ever, so
        # it is inside the first-win boost window (< first_win_boost_count=5) and
        # the intent floor is waived — every anonymous row counts: v-eligible,
        # v-low-intent, v-no-ip (the 2 identified rows are not anonymous).
        assert data["eligible_for_resolution"] == 3
        # quota trio (free tier, site default budget 50, nothing used)
        assert data["identify_used_today"] == 0
        assert data["identify_daily_limit"] == 50
        assert data["identify_is_byok"] is False


class TestResolutionSkipReason:
    @pytest.mark.asyncio
    async def test_below_intent_threshold(self, test_client, stats_setup, monkeypatch):
        # The fixture site has 0 identified visitors, so the first-win boost
        # would waive the floor entirely. Disable the boost to exercise the
        # plain floor gate (intent 10 < RESOLUTION_MIN_INTENT=20).
        from apps.api.config import settings

        monkeypatch.setattr(settings, "first_win_boost_count", 0)
        resp = await test_client.get(
            f"/api/v1/visitors/{stats_setup['site_id']}/v-low-intent",
            headers=_auth(stats_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["resolution_skip_reason"] == "below_intent_threshold"

    @pytest.mark.asyncio
    async def test_first_win_boost_waives_the_floor(self, test_client, stats_setup):
        """Boost active (site has < 5 identified ever): a low-intent visitor is
        eligible, so the skip reason is no longer below_intent_threshold."""
        resp = await test_client.get(
            f"/api/v1/visitors/{stats_setup['site_id']}/v-low-intent",
            headers=_auth(stats_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["resolution_skip_reason"] == "awaiting_next_run"

    @pytest.mark.asyncio
    async def test_no_ip_address(self, test_client, stats_setup):
        resp = await test_client.get(
            f"/api/v1/visitors/{stats_setup['site_id']}/v-no-ip",
            headers=_auth(stats_setup["token"]),
        )
        assert resp.json()["resolution_skip_reason"] == "no_ip_address"

    @pytest.mark.asyncio
    async def test_eligible_with_no_attempts_is_awaiting_next_run(
        self, test_client, stats_setup
    ):
        """The prod-bug state: eligible, never attempted → awaiting_next_run."""
        resp = await test_client.get(
            f"/api/v1/visitors/{stats_setup['site_id']}/v-eligible",
            headers=_auth(stats_setup["token"]),
        )
        data = resp.json()
        assert data["resolution_skip_reason"] == "awaiting_next_run"
        assert data["last_resolution_attempt"] is None
        assert data["resolution_providers_tried"] is None

    @pytest.mark.asyncio
    async def test_recent_attempt_surfaces_logs_and_reason(
        self, test_client, test_db, stats_setup
    ):
        from apps.api.models.visitor import ResolutionLog

        for provider in ("leadpipe", "pdl_ip_enrich"):
            test_db.add(
                ResolutionLog(
                    site_id=stats_setup["site_id"],
                    visitor_id="v-eligible",
                    provider=provider,
                    success=False,
                    cost_usd=0.01,
                )
            )
        await test_db.commit()

        resp = await test_client.get(
            f"/api/v1/visitors/{stats_setup['site_id']}/v-eligible",
            headers=_auth(stats_setup["token"]),
        )
        data = resp.json()
        assert data["resolution_skip_reason"] == "recently_attempted"
        assert data["last_resolution_attempt"] is not None
        assert set(data["resolution_providers_tried"]) == {"leadpipe", "pdl_ip_enrich"}

    @pytest.mark.asyncio
    async def test_monthly_plan_limit_reached(self, test_client, test_db, stats_setup):
        stats_setup["user"].monthly_identified_count = 10  # free plan limit
        await test_db.commit()

        resp = await test_client.get(
            f"/api/v1/visitors/{stats_setup['site_id']}/v-eligible",
            headers=_auth(stats_setup["token"]),
        )
        assert resp.json()["resolution_skip_reason"] == "monthly_plan_limit_reached"

    @pytest.mark.asyncio
    async def test_identified_visitor_has_no_skip_reason(
        self, test_client, stats_setup
    ):
        resp = await test_client.get(
            f"/api/v1/visitors/{stats_setup['site_id']}/v-enriched-new",
            headers=_auth(stats_setup["token"]),
        )
        assert resp.json()["resolution_skip_reason"] is None


@pytest_asyncio.fixture
async def bare_site(test_db):
    """User + site with no visitors — for direct helper-level tests."""
    from apps.api.models.site import Site
    from apps.api.models.user import User

    user = User(email=f"statsh-{uuidlib.uuid4().hex[:8]}@test.com", full_name="Stats Helper")
    test_db.add(user)
    await test_db.flush()
    site = Site(
        site_id=f"statsh_site_{uuidlib.uuid4().hex[:8]}",
        user_id=user.id,
        name="Stats Helper Site",
        url="https://stats-helper.example.com",
    )
    test_db.add(site)
    await test_db.commit()
    return site


class TestVisitorStatCountsHelper:
    """Direct tests of the collapsed conditional-aggregate query
    (``_compute_visitor_stat_counts``), covering cases the endpoint test above
    does not: the intent==40 boundary, could_enrich_more (enrichment_profiles),
    an empty site, and cross-site isolation. Pins the collapse to the old
    per-COUNT semantics."""

    @pytest.mark.asyncio
    async def test_counts_match_known_fixture(self, test_db, bare_site):
        from apps.api.models.enrichment import EnrichmentProfile
        from apps.api.routers.visitors import _compute_visitor_stat_counts

        sid = bare_site.site_id
        test_db.add_all([
            # identified + enriched, already segmented
            _visitor(sid, "v1", identity_status="identified", enrichment_status="enriched", segmented=True, intent_score=90),
            # identified + enriched, NOT segmented -> enriched_unsegmented
            _visitor(sid, "v2", identity_status="identified", enrichment_status="enriched", segmented=False, intent_score=80),
            # anonymous, above the floor -> eligible
            _visitor(sid, "v3", identity_status="anonymous", enrichment_status="pending", intent_score=55),
            # anonymous, below the floor -> eligible only while the boost is on
            _visitor(sid, "v4", identity_status="anonymous", enrichment_status="pending", intent_score=10),
            # anonymous, above the floor -> eligible
            _visitor(sid, "v5", identity_status="anonymous", enrichment_status="pending", intent_score=40),
            # anonymous + enriched, not segmented -> enriched + enriched_unsegmented;
            # below the floor, so eligible only while the boost is on
            _visitor(sid, "v6", identity_status="anonymous", enrichment_status="enriched", segmented=False, intent_score=12),
        ])
        test_db.add(EnrichmentProfile(site_id=sid, visitor_id="v1", enrichment_completeness=0.4))
        test_db.add(EnrichmentProfile(site_id=sid, visitor_id="v2", enrichment_completeness=0.9))
        await test_db.commit()

        counts = await _compute_visitor_stat_counts(test_db, sid)
        assert counts["total"] == 6
        assert counts["identified"] == 2               # v1, v2
        assert counts["enriched"] == 3                 # v1, v2, v6
        assert counts["enriched_unsegmented"] == 2     # v2, v6 (v1 segmented)
        # The site has 0 identified visitors ever -> inside the first-win boost
        # window, so the intent floor is waived and every anonymous row counts.
        assert counts["eligible_for_resolution"] == 4  # v3, v4, v5, v6
        assert counts["could_enrich_more"] == 1        # only the 0.4 profile

    @pytest.mark.asyncio
    async def test_eligible_counts_use_floor_when_boost_disabled(
        self, test_db, bare_site, monkeypatch
    ):
        """With the first-win boost off, eligibility is the plain floor
        (RESOLUTION_MIN_INTENT=20, >= boundary inclusive)."""
        from apps.api.config import settings
        from apps.api.models.visitor import RESOLUTION_MIN_INTENT
        from apps.api.routers.visitors import _compute_visitor_stat_counts

        monkeypatch.setattr(settings, "first_win_boost_count", 0)
        sid = bare_site.site_id
        test_db.add_all([
            _visitor(sid, "f1", identity_status="anonymous", intent_score=55),   # eligible
            _visitor(sid, "f2", identity_status="anonymous", intent_score=20),   # eligible (== floor)
            _visitor(sid, "f3", identity_status="anonymous", intent_score=19),   # NOT eligible
            _visitor(sid, "f4", identity_status="anonymous", intent_score=0),    # NOT eligible
        ])
        await test_db.commit()

        assert RESOLUTION_MIN_INTENT == 20
        counts = await _compute_visitor_stat_counts(test_db, sid)
        assert counts["total"] == 4
        assert counts["eligible_for_resolution"] == 2  # f1, f2

    @pytest.mark.asyncio
    async def test_empty_site_returns_zeros(self, test_db, bare_site):
        from apps.api.routers.visitors import _compute_visitor_stat_counts

        counts = await _compute_visitor_stat_counts(test_db, bare_site.site_id)
        assert counts == {
            "total": 0,
            "identified": 0,
            "enriched": 0,
            "could_enrich_more": 0,
            "enriched_unsegmented": 0,
            "eligible_for_resolution": 0,
            # identity-vocab-reconcile rename: company-guess rows are now
            # counted as "candidates" (was "could_enrich").
            "candidates": 0,
        }

    @pytest.mark.asyncio
    async def test_site_isolation(self, test_db, bare_site):
        from apps.api.routers.visitors import _compute_visitor_stat_counts

        sid = bare_site.site_id
        test_db.add(_visitor(sid, "v1", identity_status="identified", enrichment_status="enriched", intent_score=90))
        test_db.add(_visitor("other_site_999", "x1", identity_status="identified", enrichment_status="enriched", intent_score=90))
        await test_db.commit()

        counts = await _compute_visitor_stat_counts(test_db, sid)
        assert counts["total"] == 1
        assert counts["identified"] == 1
