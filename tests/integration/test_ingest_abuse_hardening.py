"""Integration tests for the /ingest abuse-hardening layers (P1-P5).

Requires: PostgreSQL + Redis running locally
(``docker compose -f infra/docker-compose.yml up -d postgres redis``).

Covers SPEC AC-1 .. AC-7 plus the multi-tenancy constraint. Unit-level coverage
for AC-3/AC-8 (IP resolution) and AC-6/AC-10 (velocity) lives in
``tests/unit/test_ip_resolution.py`` and ``tests/unit/test_ingest_velocity.py``.
"""

import json

import pytest
import pytest_asyncio
from sqlalchemy import select

# Realistic browser UA — is_bot("") is True, so an empty UA is silently 204'd
# before any of the hardening layers under test are reached.
_BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def test_site_id(test_db):
    """Create a test site using the ORM and return its site_id."""
    from apps.api.models.site import Site
    from apps.api.models.user import User

    result = await test_db.execute(select(User).where(User.email == "test-abuse@test.com"))
    user = result.scalar_one_or_none()
    if not user:
        user = User(email="test-abuse@test.com", full_name="Abuse Test User")
        test_db.add(user)
        await test_db.flush()

    site_id = "test_site_abuse"
    result = await test_db.execute(select(Site).where(Site.site_id == site_id))
    if not result.scalar_one_or_none():
        test_db.add(
            Site(
                site_id=site_id,
                user_id=user.id,
                name="Abuse Test Site",
                url="https://abuse-test.example.com",
            )
        )
        await test_db.flush()

    await test_db.commit()
    return site_id


def _oversized_payload(site_id: str, min_bytes: int) -> bytes:
    """A syntactically valid EventBatch whose serialized size exceeds min_bytes."""
    filler = "x" * 2000
    events = []
    approx = 0
    while approx <= min_bytes:
        events.append(
            {
                "type": "pageview",
                "url": f"https://abuse-test.example.com/{filler}",
                "page_path": "/",
                "page_title": filler,
                "user_agent": "Mozilla/5.0 Chrome/120.0.0.0",
                "ts": "2026-07-25T00:00:00",
            }
        )
        approx += 4200
    return json.dumps({"site_id": site_id, "visitor_id": "abuse-oversized", "events": events}).encode()


# ─────────────────────────── P1 — body-size guard (AC-2) ───────────────────────────


class TestOversizedBodyRejection:
    @pytest.mark.asyncio
    async def test_oversized_body_rejected(self, test_client, test_db, test_site_id):
        """AC-2: an oversized body with an honest Content-Length is rejected.

        Hits the middleware's Content-Length fast path — no body byte is read.
        """
        from apps.api.config import settings
        from apps.api.models.event import Event

        body = _oversized_payload(test_site_id, settings.ingest_body_max_bytes)
        assert len(body) > settings.ingest_body_max_bytes

        resp = await test_client.post(
            "/api/v1/events/ingest",
            content=body,
            headers={"content-type": "application/json", "user-agent": _BROWSER_UA},
        )

        assert resp.status_code not in (200, 204)
        assert resp.status_code == 413

        rows = (
            await test_db.execute(
                select(Event).where(Event.visitor_id == "abuse-oversized")
            )
        ).scalars().all()
        assert rows == []

    @pytest.mark.asyncio
    async def test_oversized_chunked_body_rejected(self, test_client, test_db, test_site_id):
        """AC-2: oversized chunked body (no Content-Length) is rejected.

        This is the scenario a Content-Length-only design silently fails: httpx
        streams a generator with Transfer-Encoding: chunked, so the ONLY guard is
        the middleware's running byte counter inside receive().
        """
        from apps.api.config import settings
        from apps.api.models.event import Event

        body = _oversized_payload(test_site_id, settings.ingest_body_max_bytes)

        async def _chunks():
            for i in range(0, len(body), 8192):
                yield body[i : i + 8192]

        resp = await test_client.post(
            "/api/v1/events/ingest",
            content=_chunks(),
            headers={"content-type": "application/json", "user-agent": _BROWSER_UA},
        )

        assert "content-length" not in {k.lower() for k in resp.request.headers}
        assert resp.status_code not in (200, 204)
        assert resp.status_code == 413

        rows = (
            await test_db.execute(
                select(Event).where(Event.visitor_id == "abuse-oversized")
            )
        ).scalars().all()
        assert rows == []

    @pytest.mark.asyncio
    async def test_normal_sized_body_still_accepted(self, test_client, test_site_id):
        """Regression: the guard must not reject a legitimate pixel batch."""
        payload = {
            "site_id": test_site_id,
            "visitor_id": "abuse-normal-001",
            "events": [
                {
                    "type": "pageview",
                    "url": "https://abuse-test.example.com/",
                    "page_path": "/",
                    "page_title": "Home",
                    "user_agent": "Mozilla/5.0 Chrome/120.0.0.0",
                    "ts": "2026-07-25T00:00:00",
                }
            ],
        }
        resp = await test_client.post(
            "/api/v1/events/ingest",
            json=payload,
            headers={"user-agent": _BROWSER_UA},
        )
        assert resp.status_code == 204


# ──────────────────── P2 — trusted-proxy IP resolution (AC-3) ────────────────────


class TestSpoofedForwardedFor:
    @pytest.mark.asyncio
    async def test_spoofed_xff_does_not_reset_rate_limit_bucket(
        self, test_client, test_site_id
    ):
        """AC-3: a per-request forged X-Forwarded-For cannot mint a fresh bucket.

        At the default ``trusted_proxy_hops = 0`` the header is ignored, so all N
        requests key on the same real socket peer and the EXISTING (unchanged)
        100/minute per-IP limiter trips at exactly the same point as if no XFF
        had been sent at all.
        """
        from apps.api.services.rate_limiter import limiter

        # conftest disables the limiter globally; this test is specifically about
        # limiter behaviour, so re-enable it and start from a clean bucket.
        limiter.enabled = True
        try:
            try:
                limiter.reset()
            except Exception:
                pass

            statuses = []
            for i in range(105):
                resp = await test_client.post(
                    "/api/v1/events/ingest",
                    json={
                        "site_id": test_site_id,
                        "visitor_id": f"xff-spoof-{i}",
                        "events": [
                            {
                                "type": "pageview",
                                "url": "https://abuse-test.example.com/",
                                "page_path": "/",
                                "ts": "2026-07-25T00:00:00",
                            }
                        ],
                    },
                    headers={
                        "user-agent": _BROWSER_UA,
                        # A DIFFERENT forged upstream IP on every single request.
                        "x-forwarded-for": f"203.0.113.{i % 254 + 1}",
                    },
                )
                statuses.append(resp.status_code)
        finally:
            limiter.enabled = False
            try:
                limiter.reset()
            except Exception:
                pass

        # Forged headers did NOT buy extra allowance: the shared bucket ran out.
        assert 429 in statuses, "forged X-Forwarded-For reset the rate-limit bucket"
        assert statuses.index(429) <= 101, (
            f"limiter tripped later than the 100/min allowance: {statuses.index(429)}"
        )


# ────────────────────── P3 — per-site ingest ceiling (AC-1) ──────────────────────


class TestSiteIngestCeiling:
    @pytest.mark.asyncio
    async def test_site_ceiling_key_func_reads_site_id(self, test_client, test_site_id):
        """The site limiter's key_func must see site_id BEFORE the limit check.

        Proves the E2 mechanism: a FastAPI ``Depends()`` resolves before the
        slowapi-wrapped endpoint runs, so ``request.state.site_id`` is populated
        by the time a site-scoped key_func would be evaluated.
        """
        import apps.api.routers.events as events_mod
        from fastapi import Request

        from apps.api.config import settings
        from apps.api.main import app
        from apps.api.routers.events import stash_site_id

        seen: list[str] = []
        stashed: list = []
        original = events_mod.site_ceiling_tripped

        def _spy(site_id: str) -> bool:
            seen.append(site_id)
            return False

        async def _stash_spy(request: Request):
            # Delegate to the REAL dependency, then capture what it actually put
            # on request.state — the value a site-scoped key_func would read.
            value = await stash_site_id(request)
            stashed.append(getattr(request.state, "site_id", "<unset>"))
            return value

        # The stash is inert unless the ceiling is enabled, so enable it here —
        # otherwise this test would assert on a deliberately-disabled code path.
        orig_enabled = settings.site_ingest_limit_enabled
        settings.site_ingest_limit_enabled = True
        events_mod.site_ceiling_tripped = _spy
        # FastAPI binds Depends() targets at route registration, so a module
        # monkeypatch would NOT take effect — use the supported override hook.
        app.dependency_overrides[stash_site_id] = _stash_spy
        try:
            resp = await test_client.post(
                "/api/v1/events/ingest",
                json={
                    "site_id": test_site_id,
                    "visitor_id": "ceiling-keyfunc-001",
                    "events": [
                        {
                            "type": "pageview",
                            "url": "https://abuse-test.example.com/",
                            "page_path": "/",
                            "ts": "2026-07-25T00:00:00",
                        }
                    ],
                },
                headers={"user-agent": _BROWSER_UA},
            )
        finally:
            events_mod.site_ceiling_tripped = original
            app.dependency_overrides.pop(stash_site_id, None)
            settings.site_ingest_limit_enabled = orig_enabled

        assert resp.status_code == 204
        assert seen == [test_site_id]
        # The E2 claim itself: the Depends() ran and populated request.state with
        # the body's site_id, which is what a site-scoped key_func reads.
        assert stashed == [test_site_id], (
            f"Depends() stash did not populate request.state.site_id: {stashed}"
        )

    @pytest.mark.asyncio
    async def test_site_ceiling_trips_on_ip_diverse_flood(
        self, test_client, test_db, test_site_id
    ):
        """AC-1: the ceiling trips on an IP-diverse flood the per-IP limiter misses.

        Every request carries a DIFFERENT source IP, so no per-IP bucket ever
        approaches its 100/min allowance — only the site-scoped ceiling sees the
        aggregate. Flag-but-store: the responses stay 204, and the excess rows are
        written with is_flagged_abuse = True.
        """
        from apps.api.config import settings
        from apps.api.models.event import Event
        from apps.api.services import rate_limiter as rl

        orig_enabled = settings.site_ingest_limit_enabled
        orig_limit = settings.site_ingest_limit_per_minute
        settings.site_ingest_limit_enabled = True
        settings.site_ingest_limit_per_minute = 5
        try:
            try:
                rl.site_limiter.reset()
            except Exception:
                pass

            statuses = []
            for i in range(12):
                resp = await test_client.post(
                    "/api/v1/events/ingest",
                    json={
                        "site_id": test_site_id,
                        "visitor_id": f"flood-visitor-{i}",
                        "events": [
                            {
                                "type": "pageview",
                                "url": "https://abuse-test.example.com/",
                                "page_path": "/",
                                "ts": "2026-07-25T00:00:00",
                            }
                        ],
                    },
                    headers={
                        "user-agent": _BROWSER_UA,
                        "x-forwarded-for": f"198.51.100.{i + 1}",
                    },
                )
                statuses.append(resp.status_code)
        finally:
            settings.site_ingest_limit_enabled = orig_enabled
            settings.site_ingest_limit_per_minute = orig_limit
            try:
                rl.site_limiter.reset()
            except Exception:
                pass

        # No per-IP bucket was anywhere near 100/min — the per-IP limiter is blind.
        assert 429 not in statuses
        assert set(statuses) == {204}

        flagged = (
            await test_db.execute(
                select(Event).where(
                    Event.site_id == test_site_id,
                    Event.visitor_id.like("flood-visitor-%"),
                    Event.is_flagged_abuse.is_(True),
                )
            )
        ).scalars().all()
        assert flagged, "site ceiling never tripped on an IP-diverse flood"


# ──────────── P4 — velocity flag, aggregator exclusion, outreach gate ────────────


async def _insert_events(db, site_id, visitor_id, count, flagged, base_minute=0):
    """Insert `count` pageview rows for a visitor, all with is_flagged_abuse=flagged."""
    from datetime import datetime, timedelta

    from apps.api.models.event import Event

    start = datetime(2026, 7, 25, 12, 0, 0) + timedelta(minutes=base_minute)
    for i in range(count):
        db.add(
            Event(
                site_id=site_id,
                visitor_id=visitor_id,
                event_type="pageview",
                url=f"https://abuse-test.example.com/p{i}",
                page_path=f"/p{i}",
                ip_address="203.0.113.5",
                scroll_depth=50,
                time_on_page=30,
                is_flagged_abuse=flagged,
                # Spread inside one 30-minute session window.
                created_at=start + timedelta(seconds=i * 10),
            )
        )
    await db.commit()


class TestAggregatorExclusionAndOutreachGate:
    @pytest.mark.asyncio
    async def test_flagged_events_excluded_from_aggregator_rollup(
        self, test_db, test_site_id
    ):
        """AC-4a: the CRITICAL raw-SQL edit — flagged rows must not inflate metrics.

        aggregate_visitors_for_site reads the events table with a raw text()
        query, bypassing the ORM entirely: adding Event.is_flagged_abuse as a
        column does NOTHING here unless that SQL itself excludes it. This test is
        written to FAIL if that exclusion is reverted — it compares a visitor with
        3 clean + 7 flagged pageviews against one with 3 clean pageviews and
        asserts they roll up identically.
        """
        from sqlalchemy import select

        from apps.api.models.visitor import Visitor
        from apps.api.services.visitor_aggregator import aggregate_visitors_for_site

        await _insert_events(test_db, test_site_id, "mixed-visitor", 3, flagged=False)
        await _insert_events(
            test_db, test_site_id, "mixed-visitor", 7, flagged=True, base_minute=1
        )
        await _insert_events(test_db, test_site_id, "clean-visitor", 3, flagged=False)

        await aggregate_visitors_for_site(test_db, test_site_id)

        rows = {
            v.visitor_id: v
            for v in (
                await test_db.execute(
                    select(Visitor).where(Visitor.site_id == test_site_id)
                )
            ).scalars().all()
        }

        mixed = rows["mixed-visitor"]
        clean = rows["clean-visitor"]

        # The 7 flagged pageviews contributed NOTHING to the rollup.
        assert mixed.total_pageviews == 3, (
            f"flagged events polluted the rollup: {mixed.total_pageviews} pageviews "
            "(expected 3 — the raw-SQL exclusion is missing or reverted)"
        )
        assert mixed.total_pageviews == clean.total_pageviews
        assert "/p5" not in (mixed.pages_visited or []), (
            "a flagged-only page leaked into pages_visited"
        )
        # ...but the visitor IS still marked, so the flag can propagate onward.
        assert mixed.is_abuse_flagged is True
        assert clean.is_abuse_flagged is False

    @pytest.mark.asyncio
    async def test_abuse_flag_propagates_event_to_identified_visitor(
        self, test_db, test_site_id
    ):
        """AC-4b (load-bearing): Event -> Visitor -> IdentifiedVisitor -> not emailable.

        Drives the REAL code path end-to-end rather than constructing a
        pre-flagged object at any step:
          1. flagged Event rows are inserted via the ORM as SETUP ONLY;
          2. the REAL aggregate_visitors_for_site runs;
          3. the Visitor is RE-FETCHED FRESH FROM THE DB (per execute-agent
             instruction E5 — the aggregator writes through raw SQL and never
             mutates an in-memory ORM instance, so reusing a pre-aggregation
             object would silently defeat this entire assertion);
          4. the REAL IdentityResolver._save_identified runs with that
             DB-confirmed visitor;
          5. is_emailable_identity is called with the value _save_identified
             itself produced.
        Every link must hold or this test fails.
        """
        from sqlalchemy import select

        from apps.api.models.visitor import IdentifiedVisitor, Visitor
        from apps.api.services.identity_classification import is_emailable_identity
        from apps.api.services.identity_resolver import IdentityResolver
        from apps.api.services.visitor_aggregator import aggregate_visitors_for_site

        visitor_id = "abuse-propagation-visitor"
        await _insert_events(test_db, test_site_id, visitor_id, 4, flagged=True)

        # 2. Real aggregation.
        await aggregate_visitors_for_site(test_db, test_site_id)

        # 3. E5: RE-FETCH from the DB. The aggregator's raw-SQL upsert never
        #    touches in-memory ORM state, so a stale object would assert on data
        #    this test supplied rather than on what the aggregator wrote.
        test_db.expire_all()
        visitor = (
            await test_db.execute(
                select(Visitor).where(
                    Visitor.site_id == test_site_id,
                    Visitor.visitor_id == visitor_id,
                )
            )
        ).scalar_one()
        assert visitor.is_abuse_flagged is True, (
            "BOOL_OR(is_flagged_abuse) -> Visitor.is_abuse_flagged did not propagate"
        )

        # 4. Real save path, with a person-level provider — the strongest case,
        #    since a person-level provider is otherwise unconditionally emailable.
        resolver = IdentityResolver(test_db)
        saved = await resolver._save_identified(
            visitor,
            {"email": "flood-suspect@example.com", "full_name": "Flood Suspect"},
            "rb2b",
        )
        assert saved is not None

        test_db.expire_all()
        identified = (
            await test_db.execute(
                select(IdentifiedVisitor).where(
                    IdentifiedVisitor.site_id == test_site_id,
                    IdentifiedVisitor.visitor_id == visitor_id,
                )
            )
        ).scalar_one()
        assert identified.is_abuse_flagged is True, (
            "Visitor.is_abuse_flagged -> IdentifiedVisitor.is_abuse_flagged did not propagate"
        )

        # 5. The guardrail itself, using the value the save path produced.
        assert (
            is_emailable_identity(
                identified.resolution_provider,
                identified.source_agent_visit_id,
                identified.is_abuse_flagged,
            )
            is False
        )

    @pytest.mark.asyncio
    async def test_flagged_identity_never_emailable(self, test_db, test_site_id):
        """AC-4 isolation-level regression for the gating logic itself (fast)."""
        from apps.api.models.visitor import IdentifiedVisitor
        from apps.api.services.identity_classification import is_emailable_identity

        iv = IdentifiedVisitor(
            site_id=test_site_id,
            visitor_id="isolated-abuse-iv",
            email="x@example.com",
            resolution_provider="rb2b",
            is_abuse_flagged=True,
        )
        test_db.add(iv)
        await test_db.commit()

        for provider in ("rb2b", "form_capture", "hunter", "apollo", None):
            iv.resolution_provider = provider
            assert (
                is_emailable_identity(provider, None, iv.is_abuse_flagged) is False
            ), provider


# ────────── P4 — velocity signal shapes (AC-5, AC-6, INNOVATE 6a/6b) ──────────


class _FakeRedis:
    def __init__(self):
        self.sets: dict[str, set] = {}

    async def sadd(self, key, member):
        self.sets.setdefault(key, set()).add(member)

    async def expire(self, key, seconds):
        pass

    async def scard(self, key):
        return len(self.sets.get(key, ()))


@pytest.fixture
def velocity_enabled():
    from apps.api.config import settings

    prev = (
        settings.ingest_velocity_enabled,
        settings.ingest_velocity_visitor_threshold,
        settings.ingest_velocity_min_fingerprint_diversity,
    )
    settings.ingest_velocity_enabled = True
    settings.ingest_velocity_visitor_threshold = 20
    settings.ingest_velocity_min_fingerprint_diversity = 0.3
    yield settings
    (
        settings.ingest_velocity_enabled,
        settings.ingest_velocity_visitor_threshold,
        settings.ingest_velocity_min_fingerprint_diversity,
    ) = prev


async def _run_shape(arrivals):
    """Feed (visitor_id, fingerprint) arrivals through check_velocity."""
    from apps.api.services.ingest_velocity import check_velocity

    redis = _FakeRedis()
    flagged = False
    for visitor_id, fp in arrivals:
        flagged = await check_velocity(redis, "shape-site", visitor_id, fp)
    return flagged


class TestVelocityShapes:
    @pytest.mark.asyncio
    async def test_organic_viral_spike_not_flagged(self, velocity_enabled):
        """AC-5: a real viral spike — many visitors, each a distinct device."""
        assert await _run_shape([(f"v{i}", f"fp2_{i}") for i in range(80)]) is False

    @pytest.mark.asyncio
    async def test_shared_nat_high_volume_high_diversity_not_flagged(
        self, velocity_enabled
    ):
        """AC-6: real humans behind one NAT/CGNAT still have distinct devices.

        IP is irrelevant to this signal by design, which is exactly why a shared
        office/CGNAT egress is not a false positive.
        """
        assert await _run_shape([(f"nat{i}", f"fp2_nat{i}") for i in range(60)]) is False

    @pytest.mark.asyncio
    async def test_shared_nat_low_diversity_flagged(self, velocity_enabled):
        """AC-6 contrast: same volume, but the identities share 2 fingerprints."""
        assert (
            await _run_shape([(f"atk{i}", f"fp2_{i % 2}") for i in range(60)]) is True
        )

    @pytest.mark.asyncio
    async def test_csv_replay_burst_not_flagged(self, velocity_enabled):
        """INNOVATE 6a: a legit replay/retry has LOW visitor diversity.

        A replay repeats a small visitor set — the OPPOSITE signature from a
        flood, which mints many new identities. Confirms high visitor count is a
        genuine precondition rather than low diversity being sufficient alone.
        """
        arrivals = [(f"v{i % 3}", f"fp2_{i % 3}") for i in range(200)]
        assert await _run_shape(arrivals) is False

    @pytest.mark.asyncio
    async def test_combined_shared_nat_and_viral_spike_composes(self, velocity_enabled):
        """INNOVATE 6b: AC-5 and AC-6 shapes together must not false-positive."""
        arrivals = [(f"viral{i}", f"fp2_viral{i}") for i in range(50)]
        arrivals += [(f"office{i}", f"fp2_office{i}") for i in range(30)]
        assert await _run_shape(arrivals) is False


# ─────────────── P5 — operator observability endpoint (AC-7 + tenancy) ───────────────


@pytest_asyncio.fixture
async def two_tenant_sites(test_db):
    """Two sites owned by DIFFERENT users, plus their owners' ids."""
    from apps.api.models.site import Site
    from apps.api.models.user import User

    created = {}
    for key, email, site_id in (
        ("flood", "op-flood@test.com", "site_flood"),
        ("organic", "op-organic@test.com", "site_organic"),
    ):
        user = (
            await test_db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if not user:
            user = User(email=email, full_name=email)
            test_db.add(user)
            await test_db.flush()
        if not (
            await test_db.execute(select(Site).where(Site.site_id == site_id))
        ).scalar_one_or_none():
            test_db.add(
                Site(
                    site_id=site_id,
                    user_id=user.id,
                    name=key,
                    url=f"https://{key}.example.com",
                )
            )
            await test_db.flush()
        created[key] = {"user_id": user.id, "email": email, "site_id": site_id}
    await test_db.commit()
    return created


class TestIngestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_ingest_health_endpoint_distinguishes_flood_from_organic(
        self, test_client, test_db, two_tenant_sites
    ):
        """AC-7: the signal must differ meaningfully between the two shapes."""
        from apps.api.dependencies import get_current_user
        from apps.api.main import app
        from apps.api.models.user import User

        flood = two_tenant_sites["flood"]
        organic = two_tenant_sites["organic"]

        # Flood site: mostly flagged traffic.
        await _insert_events(test_db, flood["site_id"], "f1", 2, flagged=False)
        await _insert_events(test_db, flood["site_id"], "f2", 18, flagged=True)
        # Organic site: same volume, zero flagged.
        await _insert_events(test_db, organic["site_id"], "o1", 20, flagged=False)

        results = {}
        for key in ("flood", "organic"):
            info = two_tenant_sites[key]
            app.dependency_overrides[get_current_user] = lambda i=info: User(
                id=i["user_id"], email=i["email"]
            )
            try:
                resp = await test_client.get(
                    f"/api/v1/sites/{info['site_id']}/ingest-health",
                    params={"window_minutes": 1440},
                )
                assert resp.status_code == 200, resp.text
                results[key] = resp.json()
            finally:
                app.dependency_overrides.pop(get_current_user, None)

        assert results["flood"]["flood_signal"] == "likely_flood"
        assert results["organic"]["flood_signal"] == "organic"
        assert results["flood"]["flagged_ratio"] > results["organic"]["flagged_ratio"]
        assert results["organic"]["flagged_events"] == 0
        # E3: limiter backend state is queryable, and never claimed as "current"
        # without a live probe alongside the process-start value.
        storage = results["flood"]["rate_limiter_storage"]
        assert {"backend_at_process_start", "redis_live_ping", "degraded"} <= set(storage)

    @pytest.mark.asyncio
    async def test_ingest_health_endpoint_tenant_scoped(
        self, test_client, two_tenant_sites
    ):
        """Multi-tenancy: a foreign site_id is 404, never 403 and never data."""
        from apps.api.dependencies import get_current_user
        from apps.api.main import app
        from apps.api.models.user import User

        flood = two_tenant_sites["flood"]
        organic = two_tenant_sites["organic"]

        app.dependency_overrides[get_current_user] = lambda: User(
            id=flood["user_id"], email=flood["email"]
        )
        try:
            foreign = await test_client.get(
                f"/api/v1/sites/{organic['site_id']}/ingest-health"
            )
            missing = await test_client.get(
                "/api/v1/sites/site_does_not_exist/ingest-health"
            )
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        assert foreign.status_code == 404
        assert missing.status_code == 404
        # Same response for foreign and non-existent — no id-existence leak.
        assert foreign.json() == missing.json()
