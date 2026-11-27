"""G4/G9/G10/G11/G13 — conversion-apis engine against real Postgres, FLAG ON.

Flag-OFF-only evidence is vacuous (E2): every test here turns
``ad_conversions_enabled`` ON and asserts the ON path actually wrote/sent rows.
Mock provider mode only (E3) — no live Meta/Google calls.
"""

import uuid as uuidlib
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text

pytestmark = pytest.mark.integration

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36"


def _naive(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


@pytest_asyncio.fixture
async def conv(test_db, monkeypatch):
    from apps.api.config import settings
    from apps.api.models.ad_connection import AdConnection
    from apps.api.models.ad_conversion import AdConversionConfig
    from apps.api.models.outcome import ConversionGoal
    from apps.api.models.site import Site
    from apps.api.models.user import User

    monkeypatch.setattr(settings, "mock_external_apis", True)
    monkeypatch.setattr(settings, "ad_conversions_enabled", True)

    user = User(email=f"conv-{uuidlib.uuid4().hex[:8]}@test.com", hashed_password="x", full_name="Conv")
    test_db.add(user)
    await test_db.flush()
    site_id = f"conv_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=site_id, user_id=user.id, name="Conv", url="https://conv.example.com"))
    await test_db.flush()
    goal = ConversionGoal(site_id=site_id, name="Demo booked", pattern="/thanks")
    test_db.add(goal)
    await test_db.flush()
    for p in ("meta", "google"):
        test_db.add(AdConnection(site_id=site_id, user_id=user.id, provider=p, auth_type="oauth", status="connected"))
    past = datetime.now(timezone.utc) - timedelta(days=2)
    test_db.add(
        AdConversionConfig(
            site_id=site_id, platform="meta", meta_dataset_id="ds-1",
            goal_event_map={"lead": "Lead", str(goal.id): "Schedule"},
            goal_watermark_at=past, lead_watermark_at=past,
        )
    )
    await test_db.commit()
    return {"site_id": site_id, "user": user, "goal": goal, "past": past}


async def _visitor(db, site_id, vid, *, provider="form_capture", status="identified",
                   country="US", email=None, ua=UA, **visitor_kw):
    from apps.api.models.event import Event
    from apps.api.models.visitor import IdentifiedVisitor, Visitor

    now = datetime.utcnow()
    db.add(Visitor(site_id=site_id, visitor_id=vid, first_seen=now - timedelta(hours=2),
                   last_seen=now, identity_status=status, country_code=country, **visitor_kw))
    iv = IdentifiedVisitor(site_id=site_id, visitor_id=vid, email=email or f"{vid}@example.com",
                           country=country, resolution_provider=provider,
                           resolved_at=now - timedelta(hours=1))
    db.add(iv)
    db.add(Event(site_id=site_id, visitor_id=vid, event_type="pageview",
                 url="https://conv.example.com/thanks?gclid=G1", user_agent=ua,
                 created_at=now - timedelta(hours=1, minutes=5)))
    await db.flush()
    return iv


async def _deliveries(db, site_id):
    from apps.api.models.ad_conversion import AdConversionDelivery

    db.expire_all()
    return (await db.execute(
        select(AdConversionDelivery).where(AdConversionDelivery.site_id == site_id)
    )).scalars().all()


# ── G4: flag-ON discovery → enqueue → sweep → sent ──


async def test_flag_on_goal_and_lead_discovery_sent_and_idempotent(test_db, conv):
    from apps.api.models.ad_conversion import AdConversionConfig
    from apps.api.models.outcome import Conversion
    from apps.api.services.ad_conversions import enqueue_conversion, run_conversion_sweep_once

    site_id = conv["site_id"]
    good = await _visitor(test_db, site_id, "v-good")
    await _visitor(test_db, site_id, "v-cand", provider="rb2b", status="candidate")
    await _visitor(test_db, site_id, "v-hunter", provider="hunter")
    await _visitor(test_db, site_id, "v-manual", provider="manual")
    conv_row = Conversion(site_id=site_id, goal_id=conv["goal"].id, visitor_id="v-good",
                          dedupe_key=f"{conv['goal'].id}:v-good", url="https://conv.example.com/thanks",
                          occurred_at=datetime.utcnow() - timedelta(minutes=30),
                          created_at=datetime.utcnow() - timedelta(minutes=30))
    test_db.add(conv_row)
    await test_db.commit()
    good_id, conv_id = str(good.id), str(conv_row.id)

    stats = await run_conversion_sweep_once(test_db)
    rows = await _deliveries(test_db, site_id)
    by_type = {(r.conversion_type, r.visitor_id): r for r in rows}
    assert set(by_type) == {("lead", "v-good"), ("goal", "v-good")}, "non-first-party/candidate enqueued"
    assert by_type[("lead", "v-good")].dedup_id == good_id
    assert by_type[("goal", "v-good")].dedup_id == conv_id
    assert all(r.status == "sent" and r.sent_at is not None for r in rows)
    assert stats["sent"] == 2

    cfg = (await test_db.execute(select(AdConversionConfig).where(AdConversionConfig.site_id == site_id))).scalar_one()
    assert cfg.goal_watermark_at > conv["past"] and cfg.lead_watermark_at > conv["past"]

    # idempotent: re-sweep and direct re-enqueue add nothing
    await run_conversion_sweep_once(test_db)
    again = await enqueue_conversion(test_db, site_id, "v-good", "lead", platform="meta",
                                     dedup_id=good_id, occurred_at=datetime.now(timezone.utc))
    await test_db.commit()
    assert again is None
    assert len(await _deliveries(test_db, site_id)) == 2


async def test_unmapped_goal_recorded_skipped_unmapped(test_db, conv):
    from apps.api.models.outcome import Conversion, ConversionGoal
    from apps.api.services.ad_conversions import run_conversion_sweep_once

    site_id = conv["site_id"]
    await _visitor(test_db, site_id, "v-u")
    other = ConversionGoal(site_id=site_id, name="Other", pattern="/x")
    test_db.add(other)
    await test_db.flush()
    test_db.add(Conversion(site_id=site_id, goal_id=other.id, visitor_id="v-u", dedupe_key=f"{other.id}:v-u",
                           occurred_at=datetime.utcnow(), created_at=datetime.utcnow() - timedelta(minutes=1)))
    await test_db.commit()
    await run_conversion_sweep_once(test_db)
    goal_rows = [r for r in await _deliveries(test_db, site_id) if r.conversion_type == "goal"]
    assert [r.status for r in goal_rows] == ["skipped_unmapped"]


async def test_retry_then_failed_after_max_attempts(test_db, conv, monkeypatch):
    from apps.api.config import settings
    from apps.api.services import ad_conversions as ac
    from apps.api.services.ads.base import ConversionResult
    from apps.api.services.ads.meta import MetaAdsProvider

    monkeypatch.setattr(settings, "ad_conversions_max_attempts", 2)

    async def flaky(self, conn, cfg, events):
        return [ConversionResult(delivery_id=e.delivery_id, ok=False, error="Provider returned HTTP 503",
                                 transient=True) for e in events]

    monkeypatch.setattr(MetaAdsProvider, "send_conversions", flaky)
    site_id = conv["site_id"]
    await _visitor(test_db, site_id, "v-retry")
    await test_db.commit()

    now = datetime.now(timezone.utc)
    await ac.run_conversion_sweep_once(test_db, now=now)
    (row,) = await _deliveries(test_db, site_id)
    assert row.status == "pending" and row.attempts == 1 and row.next_attempt_at > now
    assert row.last_error == "Provider returned HTTP 503"

    await ac.run_conversion_sweep_once(test_db, now=now + timedelta(seconds=30))  # not yet due
    (row,) = await _deliveries(test_db, site_id)
    assert row.attempts == 1

    await ac.run_conversion_sweep_once(test_db, now=now + timedelta(hours=2))
    (row,) = await _deliveries(test_db, site_id)
    assert row.status == "failed" and row.attempts == 2


async def test_foreign_site_routes_404_and_owner_200(test_db, test_client, conv):
    from apps.api.dependencies import get_current_user
    from apps.api.main import app
    from apps.api.models.user import User

    stranger = User(email=f"str-{uuidlib.uuid4().hex[:6]}@test.com", hashed_password="x", full_name="S")
    test_db.add(stranger)
    await test_db.commit()
    site_id = conv["site_id"]
    paths = [f"/api/v1/ad-conversions/{site_id}/config/meta",
             f"/api/v1/ad-conversions/{site_id}/deliveries",
             f"/api/v1/ad-conversions/{site_id}/linkedin.csv"]
    app.dependency_overrides[get_current_user] = lambda: stranger
    try:
        for p in paths:
            assert (await test_client.get(p)).status_code == 404
        assert (await test_client.put(paths[0], json={})).status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    app.dependency_overrides[get_current_user] = lambda: conv["user"]
    try:
        r = await test_client.put(f"/api/v1/ad-conversions/{site_id}/config/google",
                                  json={"goal_event_map": {"lead": "Lead"},
                                        "google_operating_account_id": "123",
                                        "google_product_destination_id": "9"})
        assert r.status_code == 200 and r.json()["validate_only"] is True
        assert (await test_client.get(paths[0])).json()["meta_dataset_id"] == "ds-1"
        assert (await test_client.get(paths[1])).json()["total"] == 0
        assert (await test_client.get(f"/api/v1/ad-conversions/{site_id}/config/tiktok")).status_code == 404
        csv = await test_client.get(paths[2])
        assert csv.status_code == 200 and csv.text.startswith("email_sha256,")
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ── G9: send-time recheck ──


async def test_recheck_gate_flips_between_enqueue_and_send_skip_with_zero_provider_calls(
    test_db, conv, monkeypatch
):
    from apps.api.config import settings
    from apps.api.models.suppression import SuppressionEntry
    from apps.api.models.visitor import IdentifiedVisitor, Visitor
    from apps.api.services import ad_conversions as ac
    from apps.api.services.ads.meta import MetaAdsProvider
    from apps.api.services.pii_crypto import email_hash

    site_id = conv["site_id"]
    flips = ["suppress", "dnr", "erase", "eea", "abuse", "bot", "agent", "internal"]
    for f in flips:
        await _visitor(test_db, site_id, f"v-{f}")
    await test_db.commit()
    for f in flips:
        status = await ac.enqueue_conversion(
            test_db, site_id, f"v-{f}", "lead", platform="meta", dedup_id=f"d-{f}",
            occurred_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        assert status == "pending"
    await test_db.commit()

    async def upd_v(vid, **kw):
        await test_db.execute(Visitor.__table__.update().where(Visitor.site_id == site_id, Visitor.visitor_id == vid).values(**kw))

    async def upd_iv(vid, **kw):
        await test_db.execute(IdentifiedVisitor.__table__.update().where(IdentifiedVisitor.site_id == site_id, IdentifiedVisitor.visitor_id == vid).values(**kw))

    test_db.add(SuppressionEntry(email_hash=email_hash("v-suppress@example.com"), scope="do_not_email",
                                 reason="test"))
    await upd_v("v-dnr", do_not_resolve=True)
    await test_db.execute(text("DELETE FROM identified_visitors WHERE site_id=:s AND visitor_id='v-erase'"), {"s": site_id})
    await upd_iv("v-eea", country="FR")
    await upd_v("v-eea", country_code="FR")
    await upd_v("v-abuse", is_abuse_flagged=True)
    await upd_v("v-bot", is_bot_suspect=True)
    await upd_iv("v-agent", source_agent_visit_id="agent-1")
    await upd_v("v-internal", internal_override="internal")
    await test_db.commit()

    calls = []

    async def spy(self, conn, cfg, events):
        calls.append(events)
        return []

    monkeypatch.setattr(MetaAdsProvider, "send_conversions", spy)
    await ac.run_conversion_sweep_once(test_db)
    status = {r.visitor_id: r.status for r in await _deliveries(test_db, site_id)}
    assert status == {
        "v-suppress": "skipped_suppressed",
        "v-dnr": "skipped_do_not_resolve",
        "v-erase": "skipped_erased",
        "v-eea": "skipped_eea",
        "v-abuse": "skipped_abuse",
        "v-bot": "skipped_bot",
        "v-agent": "skipped_agent_origin",
        "v-internal": "skipped_internal",
    }
    assert calls == []

    # flag OFF at runtime: the sweep does nothing at all
    await _visitor(test_db, site_id, "v-late")
    await test_db.commit()
    await ac.enqueue_conversion(test_db, site_id, "v-late", "lead", platform="meta",
                                dedup_id="d-late", occurred_at=datetime.now(timezone.utc))
    await test_db.commit()
    monkeypatch.setattr(settings, "ad_conversions_enabled", False)
    await ac.run_conversion_sweep_once(test_db)
    late = [r for r in await _deliveries(test_db, site_id) if r.visitor_id == "v-late"]
    assert late[0].status == "pending" and calls == []
    # …and prepare_event fails closed on the flag too
    _, skip = await ac.prepare_event(test_db, late[0], None, datetime.now(timezone.utc))
    assert skip is not None


# ── G11: provider failure never touches ingest/aggregation ──


async def test_ingest_survives_provider_and_sweep_exceptions(test_db, test_client, conv, monkeypatch):
    from apps.api.models.visitor import Visitor
    from apps.api.services import ad_conversions as ac
    from apps.api.services.ads.meta import MetaAdsProvider
    from apps.api.services.visitor_aggregator import aggregate_visitors_for_site

    async def boom(self, conn, cfg, events):
        raise RuntimeError("provider down")

    monkeypatch.setattr(MetaAdsProvider, "send_conversions", boom)
    site_id = conv["site_id"]
    await _visitor(test_db, site_id, "v-boom")
    await test_db.commit()
    await ac.run_conversion_sweep_once(test_db)  # must not raise
    (row,) = await _deliveries(test_db, site_id)
    assert row.status == "pending" and row.last_error == "send_error"

    resp = await test_client.post(
        "/api/v1/events/ingest",
        json={"site_id": site_id, "visitor_id": "v-ingest", "events": [{
            "type": "pageview", "url": "https://conv.example.com/?fbclid=FBI", "page_path": "/",
            "page_title": "Home", "user_agent": UA, "ts": "2026-11-27T00:00:00"}]},
        headers={"User-Agent": UA},
    )
    assert resp.status_code == 204
    assert await aggregate_visitors_for_site(test_db, site_id) >= 1
    test_db.expire_all()
    v = (await test_db.execute(select(Visitor).where(Visitor.site_id == site_id, Visitor.visitor_id == "v-ingest"))).scalar_one()
    assert v.click_ids and v.click_ids["fbclid"] == "FBI"


# ── G10: aggregator click_ids write-once ──


async def test_click_ids_full_and_incremental_write_once(test_db, conv):
    from apps.api.models.event import Event
    from apps.api.models.visitor import Visitor
    from apps.api.services.visitor_aggregator import aggregate_visitors_for_site

    site_id = conv["site_id"]
    base = datetime(2026, 11, 20, 10, 0, 0)

    def ev(vid, minutes, url, abuse=False):
        return Event(site_id=site_id, visitor_id=vid, event_type="pageview", url=url,
                     user_agent=UA, created_at=base + timedelta(minutes=minutes), is_flagged_abuse=abuse)

    test_db.add_all([
        # organic first, then ad click later
        ev("v-org", 0, "https://conv.example.com/"),
        ev("v-org", 5, "https://conv.example.com/p?fbclid=F2&gclid=G2"),
        # abuse-flagged click ignored, clean later click used
        ev("v-abz", 0, "https://conv.example.com/?gclid=BAD", abuse=True),
        ev("v-abz", 3, "https://conv.example.com/?wbraid=W3"),
        # never clicked
        ev("v-none", 0, "https://conv.example.com/"),
    ])
    await test_db.commit()
    await aggregate_visitors_for_site(test_db, site_id)

    async def cids(vid):
        test_db.expire_all()
        return (await test_db.execute(select(Visitor.click_ids).where(
            Visitor.site_id == site_id, Visitor.visitor_id == vid))).scalar_one()

    org = await cids("v-org")
    expected_ts = int((base + timedelta(minutes=5)).replace(tzinfo=timezone.utc).timestamp() * 1000)
    assert org == {"fbclid": "F2", "gclid": "G2", "fbc_ts": expected_ts}
    assert await cids("v-abz") == {"wbraid": "W3"}
    assert await cids("v-none") is None

    # later click events never overwrite — full recompute and incremental path
    test_db.add(ev("v-org", 60, "https://conv.example.com/?gclid=LATER"))
    test_db.add(ev("v-none", 61, "https://conv.example.com/?gbraid=GB9"))
    await test_db.commit()
    await aggregate_visitors_for_site(test_db, site_id)
    assert (await cids("v-org"))["gclid"] == "G2"
    test_db.add(ev("v-org", 120, "https://conv.example.com/?gclid=LATER2"))
    await test_db.commit()
    await aggregate_visitors_for_site(test_db, site_id, since=base + timedelta(minutes=100))
    assert (await cids("v-org"))["gclid"] == "G2"
    assert await cids("v-none") == {"gbraid": "GB9"}

    # incremental path also captures a brand-new clicker
    test_db.add(ev("v-new", 130, "https://conv.example.com/?li_fat_id=LI1"))
    await test_db.commit()
    await aggregate_visitors_for_site(test_db, site_id, since=base + timedelta(minutes=125))
    assert await cids("v-new") == {"li_fat_id": "LI1"}


# ── G13: erasure + site delete ──


async def test_erasure_removes_visitor_deliveries_and_site_delete_removes_all(test_db, test_client, conv):
    from apps.api.dependencies import get_current_user
    from apps.api.main import app
    from apps.api.services.ad_conversions import enqueue_conversion

    site_id = conv["site_id"]
    for vid in ("v-keep", "v-erase"):
        await _visitor(test_db, site_id, vid)
    await test_db.commit()
    for vid in ("v-keep", "v-erase"):
        await enqueue_conversion(test_db, site_id, vid, "lead", platform="meta",
                                 dedup_id=f"d-{vid}", occurred_at=datetime.now(timezone.utc))
    await test_db.commit()

    async def count(table, extra=""):
        return (await test_db.execute(text(f"SELECT count(*) FROM {table} WHERE site_id=:s {extra}"),
                                      {"s": site_id})).scalar_one()

    assert await count("ad_conversion_deliveries") == 2  # non-vacuous
    app.dependency_overrides[get_current_user] = lambda: conv["user"]
    try:
        r = await test_client.delete(f"/api/v1/visitors/{site_id}/v-erase/data")
        assert r.status_code == 200
        assert await count("ad_conversion_deliveries", "AND visitor_id='v-erase'") == 0
        assert await count("ad_conversion_deliveries", "AND visitor_id='v-keep'") == 1
        assert await count("ad_conversion_configs") == 1
        r = await test_client.delete(f"/api/v1/sites/{site_id}")
        assert r.status_code == 204
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert await count("ad_conversion_deliveries") == 0
    assert await count("ad_conversion_configs") == 0
