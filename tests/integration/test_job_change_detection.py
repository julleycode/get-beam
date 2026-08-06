"""Integration tests for job-change detection v1 (same-tenant).

Covers SPEC AC-1 (flag-off no-op), AC-2 (event-driven re-check), AC-3 (stale
sweep selection), AC-4 (budget isolation), AC-7 (minimal before/after row +
in-place profile update), AC-8 (draft-only, zero send), AC-11 (zero
beam_identity_graph access) and AC-12 (erasure cascade, extended to prove the
whole pre-existing table tuple still deletes — the erasure endpoint had NO
automated regression coverage before this file).

Requires local PostgreSQL + Redis (docker compose -f infra/docker-compose.yml
up -d postgres redis).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from apps.api.models.enrichment import EnrichmentProfile
from apps.api.models.job_change_event import JobChangeEvent
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.services import job_change_detector as jcd

pytestmark = pytest.mark.integration

SITE_ID = "site_jobchange"
VISITOR_ID = "v_jobchange_1"
EMAIL = "person@acme.com"


class _FakeRedis:
    """In-memory Redis so the budget counter is deterministic and isolated."""

    def __init__(self):
        self.store: dict[str, int] = {}

    async def get(self, key):
        return self.store.get(key)

    async def incr(self, key):
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def decr(self, key):
        self.store[key] = self.store.get(key, 0) - 1
        return self.store[key]

    async def expire(self, key, ttl):
        return True


@pytest.fixture
def open_gates(monkeypatch):
    """All 4 safety gates open + an isolated Redis. Individual tests close one."""
    async def _no(ip):
        return False

    async def _privacy(ip):
        return {}

    async def _not_suppressed(db, email, scope):
        return False

    monkeypatch.setattr(jcd, "is_datacenter_ip", _no)
    monkeypatch.setattr(jcd, "check_ip_privacy", _privacy)
    monkeypatch.setattr(jcd, "is_proxy_or_vpn", lambda p: False)
    monkeypatch.setattr(jcd, "is_email_suppressed", _not_suppressed)
    monkeypatch.setattr(jcd, "get_redis", lambda: _FakeRedis())
    return monkeypatch


@pytest.fixture
def provider_returns_new_company(monkeypatch):
    """PDL reports the person now works at Globex."""
    async def _fresh(db, visitor, email):
        return ({"company_name": "Globex", "job_title": "Staff Engineer"}, "pdl")

    monkeypatch.setattr(jcd, "_fetch_fresh_profile", _fresh)
    return monkeypatch


@pytest_asyncio.fixture
async def seeded(test_db):
    """One site + owner + identified visitor with an 'Acme' baseline profile."""
    user = User(id=uuid.uuid4(), email=f"owner-{uuid.uuid4().hex[:6]}@example.com")
    test_db.add(user)
    await test_db.flush()

    site = Site(site_id=SITE_ID, user_id=user.id, name="JobChange Co", url="https://x.test")
    visitor = Visitor(
        site_id=SITE_ID,
        visitor_id=VISITOR_ID,
        ip_address="203.0.113.7",
        identity_status="identified",
        do_not_resolve=False,
    )
    identified = IdentifiedVisitor(
        site_id=SITE_ID, visitor_id=VISITOR_ID, email=EMAIL, full_name="Pat Person"
    )
    profile = EnrichmentProfile(
        site_id=SITE_ID,
        visitor_id=VISITOR_ID,
        company_name="Acme",
        job_title="Engineer",
        enriched_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=200),
    )
    test_db.add_all([site, visitor, identified, profile])
    await test_db.commit()
    return {"db": test_db, "site": site, "visitor": visitor, "user": user}


async def _count_events(db) -> int:
    return len(
        (
            await db.execute(
                select(JobChangeEvent).where(JobChangeEvent.site_id == SITE_ID)
            )
        ).scalars().all()
    )


# ───────────────────────────── AC-1: flag OFF ────────────────────────────────


async def test_flag_off_zero_activity(seeded, open_gates, provider_returns_new_company, monkeypatch):
    """Flag off → no row written, even for a visitor who otherwise qualifies."""
    monkeypatch.setattr(jcd.settings, "job_change_detection_enabled", False)
    result = await jcd.run_recheck(seeded["db"], seeded["visitor"], seeded["site"])
    assert result is None
    assert await _count_events(seeded["db"]) == 0


async def test_flag_off_blocks_provider_call_entirely(seeded, open_gates, monkeypatch):
    """Flag off must short-circuit BEFORE any paid provider call is made."""
    called = {"n": 0}

    async def _spy(db, visitor, email):
        called["n"] += 1
        return ({"company_name": "Globex"}, "pdl")

    monkeypatch.setattr(jcd, "_fetch_fresh_profile", _spy)
    monkeypatch.setattr(jcd.settings, "job_change_detection_enabled", False)
    await jcd.run_recheck(seeded["db"], seeded["visitor"], seeded["site"])
    assert called["n"] == 0


# ────────────────────── AC-2 / AC-7: detect + record ─────────────────────────


async def test_confirmed_change_writes_minimal_row(
    seeded, open_gates, provider_returns_new_company, monkeypatch
):
    """AC-7: exactly one row with correct before/after, profile updated in place."""
    monkeypatch.setattr(jcd.settings, "job_change_detection_enabled", True)
    db = seeded["db"]

    event = await jcd.run_recheck(db, seeded["visitor"], seeded["site"])

    assert event is not None
    assert await _count_events(db) == 1
    assert event.prior_company == "Acme"
    assert event.new_company == "Globex"
    assert event.prior_job_title == "Engineer"
    assert event.new_job_title == "Staff Engineer"
    assert event.corroboration_signal == "work_email_domain"
    assert event.confidence >= 0.5

    profile = (
        await db.execute(
            select(EnrichmentProfile).where(
                EnrichmentProfile.site_id == SITE_ID,
                EnrichmentProfile.visitor_id == VISITOR_ID,
            )
        )
    ).scalar_one()
    assert profile.company_name == "Globex"
    assert profile.job_title == "Staff Engineer"


async def test_event_driven_recheck_fires(
    seeded, open_gates, provider_returns_new_company, monkeypatch
):
    """AC-2: the Trigger A task path reaches detection for a returning visitor."""
    monkeypatch.setattr(jcd.settings, "job_change_detection_enabled", True)
    from apps.api.tasks import job_change_tasks

    # The task normally opens its own session; point it at the test session so
    # the seeded rows are visible.
    class _Ctx:
        def __init__(self, db):
            self.db = db

        async def __aenter__(self):
            return self.db

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(job_change_tasks, "async_session", lambda: _Ctx(seeded["db"]))
    result = await job_change_tasks._recheck_one(VISITOR_ID, SITE_ID)
    assert result["detected"] == 1


async def test_no_material_change_writes_no_row(seeded, open_gates, monkeypatch):
    """Same employer, differently punctuated → not a job change."""
    monkeypatch.setattr(jcd.settings, "job_change_detection_enabled", True)

    async def _same(db, visitor, email):
        return ({"company_name": "Acme, Inc."}, "pdl")

    monkeypatch.setattr(jcd, "_fetch_fresh_profile", _same)
    assert await jcd.run_recheck(seeded["db"], seeded["visitor"], seeded["site"]) is None
    assert await _count_events(seeded["db"]) == 0


async def test_uncorroborated_change_writes_no_row(seeded, open_gates, monkeypatch):
    """AC-6 end-to-end: personal-mailbox-only evidence never records a change."""
    monkeypatch.setattr(jcd.settings, "job_change_detection_enabled", True)
    db = seeded["db"]

    identified = (
        await db.execute(
            select(IdentifiedVisitor).where(IdentifiedVisitor.visitor_id == VISITOR_ID)
        )
    ).scalar_one()
    identified.email = "person@gmail.com"
    await db.commit()

    async def _fresh(db_, visitor, email):
        return ({"company_name": "Globex"}, "pdl")

    monkeypatch.setattr(jcd, "_fetch_fresh_profile", _fresh)
    assert await jcd.run_recheck(db, seeded["visitor"], seeded["site"]) is None
    assert await _count_events(db) == 0


# ─────────────────────────── AC-3: stale sweep ───────────────────────────────


async def test_sweep_selects_bounded_subset(seeded):
    """AC-3: stale, identified, non-opted-out visitors are selected, bounded."""
    db = seeded["db"]
    stale = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=200)

    # A fresh profile (not stale), an opted-out visitor, and an anonymous one —
    # none of the three may be selected.
    for vid, status, dnr, enriched in [
        ("v_fresh", "identified", False, datetime.now(timezone.utc).replace(tzinfo=None)),
        ("v_optout", "identified", True, stale),
        ("v_anon", "anonymous", False, stale),
        ("v_stale_2", "identified", False, stale),
    ]:
        db.add(Visitor(site_id=SITE_ID, visitor_id=vid, identity_status=status, do_not_resolve=dnr))
        db.add(
            EnrichmentProfile(
                site_id=SITE_ID, visitor_id=vid, company_name="Acme", enriched_at=enriched
            )
        )
    await db.commit()

    rows = (await db.execute(jcd.select_stale_visitors_query(site_id=SITE_ID, limit=10))).all()
    selected = {v.visitor_id for v, _ in rows}

    assert VISITOR_ID in selected
    assert "v_stale_2" in selected
    assert "v_fresh" not in selected
    assert "v_optout" not in selected  # AC-13 at the query level
    assert "v_anon" not in selected

    bounded = (await db.execute(jcd.select_stale_visitors_query(site_id=SITE_ID, limit=1))).all()
    assert len(bounded) == 1


# ──────────────────────── AC-4: budget isolation ─────────────────────────────


async def test_budget_cap_isolated_from_resolution_budget(
    seeded, open_gates, provider_returns_new_company, monkeypatch
):
    """AC-4: exceeding the re-check cap refuses further work and leaves
    Site.daily_resolution_budget completely untouched."""
    monkeypatch.setattr(jcd.settings, "job_change_detection_enabled", True)
    monkeypatch.setattr(jcd.settings, "job_change_recheck_daily_cap", 1)
    db = seeded["db"]
    budget_before = seeded["site"].daily_resolution_budget

    shared = _FakeRedis()
    monkeypatch.setattr(jcd, "get_redis", lambda: shared)

    first = await jcd.run_recheck(db, seeded["visitor"], seeded["site"])
    assert first is not None

    # Reset the baseline so a second run is otherwise eligible; only the budget
    # should stop it.
    profile = (
        await db.execute(
            select(EnrichmentProfile).where(EnrichmentProfile.visitor_id == VISITOR_ID)
        )
    ).scalar_one()
    profile.company_name = "Acme"
    await db.commit()

    second = await jcd.run_recheck(db, seeded["visitor"], seeded["site"])
    assert second is None
    assert await _count_events(db) == 1

    site = (await db.execute(select(Site).where(Site.site_id == SITE_ID))).scalar_one()
    assert site.daily_resolution_budget == budget_before


# ──────────────────────── AC-8: draft only, never send ───────────────────────


async def test_confirmed_change_creates_draft_only(
    seeded, open_gates, provider_returns_new_company, monkeypatch
):
    """AC-8: a confirmed change produces a pending DRAFT and zero send calls."""
    monkeypatch.setattr(jcd.settings, "job_change_detection_enabled", True)
    monkeypatch.setattr(jcd.settings, "mock_external_apis", True)
    db = seeded["db"]

    sent = {"n": 0}
    import apps.api.services.email_sender as email_sender

    async def _spy_send(*a, **kw):
        sent["n"] += 1
        return True

    monkeypatch.setattr(email_sender, "send_email", _spy_send, raising=False)

    event = await jcd.run_recheck(db, seeded["visitor"], seeded["site"])
    assert event is not None

    from apps.api.models.draft import Draft, DraftStatus

    drafts = (
        await db.execute(select(Draft).where(Draft.visitor_id == VISITOR_ID))
    ).scalars().all()
    assert len(drafts) == 1
    assert drafts[0].status == DraftStatus.pending
    assert drafts[0].auto_generated is True
    assert sent["n"] == 0


async def test_draft_failure_does_not_lose_the_detection(
    seeded, open_gates, provider_returns_new_company, monkeypatch
):
    """The event row must survive a draft-generation blow-up."""
    monkeypatch.setattr(jcd.settings, "job_change_detection_enabled", True)

    async def _boom(db, **kw):
        raise RuntimeError("drafting exploded")

    monkeypatch.setattr(jcd, "_trigger_job_change_draft", _boom)
    event = await jcd.run_recheck(seeded["db"], seeded["visitor"], seeded["site"])
    assert event is not None
    assert await _count_events(seeded["db"]) == 1


# ─────────────────── AC-11: zero beam_identity_graph access ──────────────────


async def test_no_beam_identity_graph_access(
    seeded, open_gates, provider_returns_new_company, monkeypatch
):
    """AC-11: detection touches beam_identity_graph zero times, even when a
    matching cross-tenant row for the same person exists."""
    monkeypatch.setattr(jcd.settings, "job_change_detection_enabled", True)
    db = seeded["db"]

    from apps.api.models.beam_identity import BeamIdentityNode

    db.add(
        BeamIdentityNode(
            fingerprint="fp2_other_tenant",
            email=EMAIL,
            full_name="Pat Person",
            confidence_score=0.9,
            source_site_id="some_other_tenant_site",
            source_provider="leadpipe",
        )
    )
    await db.commit()

    import apps.api.services.identity_resolver as identity_resolver

    touched = {"n": 0}
    if hasattr(identity_resolver, "_upsert_beam_identity"):
        async def _spy(*a, **kw):
            touched["n"] += 1

        monkeypatch.setattr(identity_resolver, "_upsert_beam_identity", _spy, raising=False)

    before = len((await db.execute(select(BeamIdentityNode))).scalars().all())
    event = await jcd.run_recheck(db, seeded["visitor"], seeded["site"])
    after_rows = (await db.execute(select(BeamIdentityNode))).scalars().all()

    assert event is not None  # detection still worked same-tenant
    assert touched["n"] == 0
    assert len(after_rows) == before
    # The cross-tenant row was neither consumed nor mutated.
    assert after_rows[0].source_site_id == "some_other_tenant_site"


# ────────────────────────── AC-12: erasure cascade ───────────────────────────


async def test_erasure_cascade_deletes_job_change_events(seeded, test_client, monkeypatch):
    """AC-12 + regression: the DELETE endpoint removes the new job_change_events
    row AND every pre-existing table in the tuple.

    This doubles as the FIRST automated regression proof for delete_visitor_data
    — before this test the endpoint had zero coverage (confirmed at VALIDATE).
    """
    db = seeded["db"]
    db.add(
        JobChangeEvent(
            site_id=SITE_ID,
            visitor_id=VISITOR_ID,
            prior_company="Acme",
            new_company="Globex",
            confidence=0.8,
            corroboration_signal="work_email_domain",
        )
    )
    await db.commit()

    tables = (
        "identified_visitors",
        "enrichment_profiles",
        "job_change_events",
        "visitors",
    )
    for t in tables:
        n = (
            await db.execute(
                text(f"SELECT count(*) FROM {t} WHERE site_id=:s AND visitor_id=:v"),
                {"s": SITE_ID, "v": VISITOR_ID},
            )
        ).scalar_one()
        assert n > 0, f"{t} was not seeded — the assertion below would be vacuous"

    from apps.api.dependencies import get_current_user
    from apps.api.main import app

    app.dependency_overrides[get_current_user] = lambda: seeded["user"]
    try:
        resp = await test_client.delete(f"/api/v1/visitors/{SITE_ID}/{VISITOR_ID}/data")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 200
    assert "job_change_events" in resp.json()["deleted"]

    for t in tables:
        n = (
            await db.execute(
                text(f"SELECT count(*) FROM {t} WHERE site_id=:s AND visitor_id=:v"),
                {"s": SITE_ID, "v": VISITOR_ID},
            )
        ).scalar_one()
        assert n == 0, f"{t} rows survived erasure"


# ──────────────────────── AC-10: segmenter signal ────────────────────────────


async def test_job_changed_at_signal_readable(seeded):
    """AC-10: a confirmed change surfaces as an additive segmenter signal."""
    db = seeded["db"]
    db.add(
        JobChangeEvent(
            site_id=SITE_ID,
            visitor_id=VISITOR_ID,
            prior_company="Acme",
            new_company="Globex",
            confidence=0.8,
        )
    )
    await db.commit()

    from apps.api.agents.segmenter import build_visitor_profiles

    profiles = await build_visitor_profiles(db, SITE_ID, [seeded["visitor"]])
    assert len(profiles) == 1
    assert profiles[0]["job_changed_at"] is not None
    # Signal, not bypass: the intent score is untouched.
    assert profiles[0]["intent_score"] == seeded["visitor"].intent_score


async def test_job_changed_at_is_none_without_an_event(seeded):
    from apps.api.agents.segmenter import build_visitor_profiles

    profiles = await build_visitor_profiles(seeded["db"], SITE_ID, [seeded["visitor"]])
    assert profiles[0]["job_changed_at"] is None


# ─────────────────────── surfacing endpoint (US-1/US-2) ──────────────────────


async def test_job_changes_endpoint_is_site_scoped(seeded, test_client):
    db = seeded["db"]
    db.add(
        JobChangeEvent(
            site_id=SITE_ID, visitor_id=VISITOR_ID, prior_company="Acme", new_company="Globex"
        )
    )
    db.add(
        JobChangeEvent(
            site_id="some_other_site", visitor_id="v_other", prior_company="X", new_company="Y"
        )
    )
    await db.commit()

    from apps.api.dependencies import get_current_user
    from apps.api.main import app

    app.dependency_overrides[get_current_user] = lambda: seeded["user"]
    try:
        resp = await test_client.get(f"/api/v1/sites/{SITE_ID}/job-changes")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["events"][0]["new_company"] == "Globex"
    # AC-14 at the API boundary: no PII fields leak into the feed.
    assert "email" not in body["events"][0]
