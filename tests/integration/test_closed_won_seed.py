"""G3 + G8 — closed-won seed + lookalike against real Postgres, FLAG ON.

Flag-OFF-only evidence is vacuous (E3): every behavior here runs with
``closed_won_lookalikes_enabled`` ON. Mock provider mode only (E2).
"""

import hashlib
import hmac
import json
import uuid as uuidlib
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select

pytestmark = pytest.mark.integration

SECRET = "whsec_test_closed_won"


@pytest_asyncio.fixture
async def cw(test_db, monkeypatch):
    from apps.api.config import settings
    from apps.api.models.ad_connection import AdConnection
    from apps.api.models.crm_connection import CrmConnection
    from apps.api.models.site import Site
    from apps.api.models.user import User
    from apps.api.services.key_vault import encrypt_key

    monkeypatch.setattr(settings, "mock_external_apis", True)
    monkeypatch.setattr(settings, "closed_won_lookalikes_enabled", True)
    monkeypatch.setattr(settings, "ad_audiences_enabled", True)

    user = User(email=f"cw-{uuidlib.uuid4().hex[:8]}@test.com", hashed_password="x", full_name="CW")
    test_db.add(user)
    await test_db.flush()
    site_id = f"cw_{uuidlib.uuid4().hex[:8]}"
    other_site = f"cwo_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=site_id, user_id=user.id, name="CW", url="https://cw.example.com"))
    test_db.add(Site(site_id=other_site, user_id=user.id, name="CWO", url="https://cwo.example.com"))
    await test_db.flush()
    for p in ("meta", "google"):
        test_db.add(AdConnection(site_id=site_id, user_id=user.id, provider=p,
                                 auth_type="oauth", status="connected"))
    test_db.add(CrmConnection(site_id=site_id, user_id=user.id, provider="generic_webhook",
                              auth_type="webhook", status="connected",
                              webhook_url="https://hooks.example.com/x",
                              encrypted_secret=encrypt_key(SECRET)))
    test_db.add(CrmConnection(site_id=site_id, user_id=user.id, provider="hubspot",
                              auth_type="oauth", status="connected",
                              scopes=["crm.objects.deals.read"]))
    await test_db.commit()
    # Detached stand-in: later commits expire the ORM user, and an expired
    # attribute lazy-loads outside the request's greenlet.
    from types import SimpleNamespace

    principal = SimpleNamespace(id=user.id, email=user.email)
    return {"site_id": site_id, "other": other_site, "user": principal}


@pytest_asyncio.fixture
async def owner(cw):
    from apps.api.dependencies import get_current_user
    from apps.api.main import app

    app.dependency_overrides[get_current_user] = lambda: cw["user"]
    yield
    app.dependency_overrides.pop(get_current_user, None)


async def _identified(db, site_id, vid, email, *, provider="form_capture", country="US",
                      dnr=False, **iv_kw):
    from apps.api.models.visitor import IdentifiedVisitor, Visitor
    from apps.api.services.pii_crypto import email_hash

    now = datetime.utcnow()
    db.add(Visitor(site_id=site_id, visitor_id=vid, first_seen=now - timedelta(hours=2),
                   last_seen=now, identity_status="identified", country_code=country,
                   do_not_resolve=dnr))
    db.add(IdentifiedVisitor(site_id=site_id, visitor_id=vid, email=email, email_bidx=email_hash(email),
                             country=country, resolution_provider=provider,
                             resolved_at=now - timedelta(hours=1), **iv_kw))
    await db.flush()


async def _contacts(db, site_id):
    from apps.api.models.crm_closed_won import CrmClosedWonContact

    db.expire_all()
    return (await db.execute(
        select(CrmClosedWonContact).where(CrmClosedWonContact.site_id == site_id)
    )).scalars().all()


async def _links(db, site_id, provider="meta"):
    from apps.api.models.ad_audience_link import AdAudienceLink
    from apps.api.models.ad_connection import AdConnection

    db.expire_all()
    return (await db.execute(
        select(AdAudienceLink).join(AdConnection, AdConnection.id == AdAudienceLink.connection_id)
        .where(AdConnection.site_id == site_id, AdConnection.provider == provider)
    )).scalars().all()


def _sign(body: bytes) -> str:
    return hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


# ── G3: sync -> match -> exclusions -> seed -> lookalike ──


async def test_flag_on_poll_match_seed_lookalike_and_repeat_semantics(
    test_db, test_client, cw, owner, monkeypatch
):
    from apps.api.services import closed_won_seed
    from apps.api.services.ads.meta import MetaAdsProvider
    from apps.api.services.closed_won_seed import poll_closed_won_once

    site_id = cw["site_id"]
    # Poll (mock HubSpot returns 3 deals); one of them matches an identified visitor.
    await _identified(test_db, site_id, "v-buyer1", "buyer1@hubspot-customer.example")
    await test_db.commit()
    stats = await poll_closed_won_once(test_db)
    assert stats["connections"] == 1
    assert len(await _contacts(test_db, site_id)) == 3
    # No plaintext at rest.
    for c in await _contacts(test_db, site_id):
        assert "@" not in c.email_ciphertext and len(c.email_bidx) == 64

    seed = (await test_client.get(f"/api/v1/ads/{site_id}/closed-won/seed")).json()
    assert seed == {"total": 3, "matched": 1, "eligible": 3, "excluded": 0, "needs_reconnect": False}

    calls = {"audience": 0, "lookalike": 0}
    orig_aud = MetaAdsProvider.create_or_update_audience
    orig_lal = MetaAdsProvider.create_lookalike

    async def count_aud(self, *a, **k):
        calls["audience"] += 1
        return await orig_aud(self, *a, **k)

    async def count_lal(self, *a, **k):
        calls["lookalike"] += 1
        return await orig_lal(self, *a, **k)

    monkeypatch.setattr(MetaAdsProvider, "create_or_update_audience", count_aud)
    monkeypatch.setattr(MetaAdsProvider, "create_lookalike", count_lal)

    url = f"/api/v1/ads/{site_id}/closed-won/lookalike"
    r1 = await test_client.post(url, json={"provider": "meta", "country": "US", "ratio": "0.05"})
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert b1["seed_pushed"] == 3 and b1["lookalike_audience_id"].startswith("mock-meta-lal-")
    assert "at least" in b1["warning"]  # <100 seed warning
    links = await _links(test_db, site_id)
    assert sorted(l.segment_id for l in links) == ["closed_won_lookalike:US:0.05", "closed_won_seed"]
    assert calls == {"audience": 1, "lookalike": 1}

    # Same spec -> stored id, zero adapter calls.
    r2 = (await test_client.post(url, json={"provider": "meta", "country": "US", "ratio": "0.05"})).json()
    assert r2["lookalike_audience_id"] == b1["lookalike_audience_id"] and r2["reused"] is True
    assert calls == {"audience": 1, "lookalike": 1}

    # Different ratio -> new id, previous returned, still one lookalike row.
    r3 = (await test_client.post(url, json={"provider": "meta", "country": "US", "ratio": "0.10"})).json()
    assert r3["lookalike_audience_id"] != b1["lookalike_audience_id"]
    assert r3["previous_lookalike_id"] == b1["lookalike_audience_id"]
    links = await _links(test_db, site_id)
    assert sorted(l.segment_id for l in links) == ["closed_won_lookalike:US:0.10", "closed_won_seed"]
    assert calls == {"audience": 1, "lookalike": 2}

    # E7 allow-list: bad ratio / country -> 422, nothing written.
    for bad in ({"ratio": "0.5", "country": "US"}, {"ratio": "0.05", "country": "U%"},
                {"ratio": "0.05:x", "country": "US"}):
        r = await test_client.post(url, json={"provider": "meta", **bad})
        assert r.status_code == 422, bad
    assert closed_won_seed.LOOKALIKE_PREFIX == "closed_won_lookalike:"


async def test_google_lookalike_excludes_eea_and_unknown_country(test_db, test_client, cw, owner):
    from apps.api.services.closed_won_seed import build_seed, ingest_deals
    from apps.api.services.crm.base import ClosedWonDeal

    site_id = cw["site_id"]
    await ingest_deals(test_db, site_id, [
        ClosedWonDeal("d1", "us@x.example", country="US"),
        ClosedWonDeal("d2", "de@x.example", country="DE"),
        ClosedWonDeal("d3", "nocountry@x.example"),
    ], source="csv")
    build = await build_seed(test_db, site_id, google=True)
    assert [r.email for r in build.rows] == ["us@x.example"] and build.excluded == 2
    r = await test_client.post(f"/api/v1/ads/{site_id}/closed-won/lookalike",
                               json={"provider": "google", "country": "US", "expansion": "BALANCED"})
    assert r.status_code == 200 and r.json()["seed_pushed"] == 1
    assert "Demand Gen" in r.json()["warning"]
    r = await test_client.post(f"/api/v1/ads/{site_id}/closed-won/lookalike",
                               json={"provider": "google", "country": "FR", "expansion": "BROAD"})
    assert r.status_code == 200 and "EEA" in r.json()["error"]


async def test_flag_gating_and_tenant_isolation(test_db, test_client, cw, monkeypatch):
    from apps.api.config import settings
    from apps.api.dependencies import get_current_user
    from apps.api.main import app
    from apps.api.models.user import User

    site_id = cw["site_id"]
    lal = f"/api/v1/ads/{site_id}/closed-won/lookalike"
    body = {"provider": "meta", "country": "US", "ratio": "0.05"}
    app.dependency_overrides[get_current_user] = lambda: cw["user"]
    try:
        monkeypatch.setattr(settings, "ad_audiences_enabled", False)
        assert (await test_client.post(lal, json=body)).status_code == 501
        assert (await test_client.get(f"/api/v1/ads/{site_id}/closed-won/seed")).status_code == 200
        monkeypatch.setattr(settings, "closed_won_lookalikes_enabled", False)
        for method, path in (("get", "seed"), ("get", "linkedin.csv"), ("post", "csv"), ("post", "lookalike")):
            kw = {"json": {"csv": "email\n"}} if path == "csv" else ({"json": body} if method == "post" else {})
            r = await getattr(test_client, method)(f"/api/v1/ads/{site_id}/closed-won/{path}", **kw)
            assert r.status_code == 404, path
        r = await test_client.post(f"/api/v1/crm/{site_id}/webhook/deal", content=b"{}")
        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    monkeypatch.setattr(settings, "closed_won_lookalikes_enabled", True)
    monkeypatch.setattr(settings, "ad_audiences_enabled", True)
    stranger = User(email=f"s-{uuidlib.uuid4().hex[:6]}@test.com", hashed_password="x", full_name="S")
    test_db.add(stranger)
    await test_db.commit()
    app.dependency_overrides[get_current_user] = lambda: stranger
    try:
        assert (await test_client.get(f"/api/v1/ads/{site_id}/closed-won/seed")).status_code == 404
        assert (await test_client.post(lal, json=body)).status_code == 404
        assert (await test_client.post(f"/api/v1/ads/{site_id}/closed-won/csv",
                                       json={"csv": "email\na@b.example\n"})).status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def test_csv_upload_and_linkedin_export(test_db, test_client, cw, owner):
    site_id = cw["site_id"]
    r = await test_client.post(f"/api/v1/ads/{site_id}/closed-won/csv",
                               json={"csv": "email,country\nA@B.example,US\nnot-an-email,US\n"})
    assert r.status_code == 200 and r.json() == {"upserted": 1, "skipped_erased": 0, "skipped_invalid": 1}
    r = await test_client.post(f"/api/v1/ads/{site_id}/closed-won/csv", json={"csv": "name\nx\n"})
    assert r.status_code == 422
    csv = await test_client.get(f"/api/v1/ads/{site_id}/closed-won/linkedin.csv")
    assert csv.status_code == 200
    lines = csv.text.strip().splitlines()
    assert lines[0] == "email_sha256" and lines[1] == hashlib.sha256(b"a@b.example").hexdigest()
    assert "a@b.example" not in csv.text


# ── webhook (N3) ──


async def test_webhook_order_hmac_size_replay_and_limit(test_db, test_client, cw):
    from apps.api.services.rate_limiter import limiter

    site_id = cw["site_id"]
    url = f"/api/v1/crm/{site_id}/webhook/deal"
    payload = json.dumps({"deal_id": "deal-77", "emails": ["wh@x.example"], "country": "US"}).encode()

    # declared AND actual oversize -> 413
    big = b"{" + b" " * (256 * 1024 + 10) + b"}"
    assert (await test_client.post(url, content=big, headers={"X-Beam-Signature": _sign(big)})).status_code == 413
    r = await test_client.post(url, content=payload,
                               headers={"Content-Length": str(300 * 1024), "X-Beam-Signature": _sign(payload)})
    assert r.status_code == 413

    # no generic_webhook connection on the other site -> 404
    r = await test_client.post(f"/api/v1/crm/{cw['other']}/webhook/deal", content=payload,
                               headers={"X-Beam-Signature": _sign(payload)})
    assert r.status_code == 404

    # bad / missing HMAC -> 400
    assert (await test_client.post(url, content=payload, headers={"X-Beam-Signature": "00"})).status_code == 400
    assert (await test_client.post(url, content=payload)).status_code == 400

    # good + replay -> one row
    for _ in range(2):
        r = await test_client.post(url, content=payload, headers={"X-Beam-Signature": _sign(payload)})
        assert r.status_code == 202 and r.json()["accepted"] == 1
    rows = await _contacts(test_db, site_id)
    assert len(rows) == 1 and rows[0].source == "webhook" and rows[0].external_deal_id == "deal-77"

    # rate limit registered on the route
    assert any("closed_won_deal_webhook" in k for k in limiter._route_limits)


async def test_erased_tombstone_is_never_ingested(test_db, cw):
    from apps.api.models.suppression import SuppressionEntry
    from apps.api.services.closed_won_seed import ingest_deals
    from apps.api.services.crm.base import ClosedWonDeal
    from apps.api.services.pii_crypto import email_hash

    test_db.add(SuppressionEntry(email_hash=email_hash("gone@x.example"), scope="erased"))
    await test_db.commit()
    out = await ingest_deals(test_db, cw["site_id"], [
        ClosedWonDeal("d1", "gone@x.example"), ClosedWonDeal("d1", "kept@x.example")
    ], source="crm")
    assert out.upserted == 1 and out.skipped_erased == 1
    assert len(await _contacts(test_db, cw["site_id"])) == 1


async def test_same_bidx_visitor_on_another_site_is_not_matched(test_db, cw):
    from apps.api.services.closed_won_seed import build_seed, ingest_deals
    from apps.api.services.crm.base import ClosedWonDeal

    await _identified(test_db, cw["other"], "v-x", "shared@x.example")
    await test_db.commit()
    await ingest_deals(test_db, cw["site_id"], [ClosedWonDeal("d1", "shared@x.example")], source="csv")
    build = await build_seed(test_db, cw["site_id"])
    assert build.matched == 0 and len(build.rows) == 1 and build.rows[0].matched is False


# ── G8: exclusion matrix ──


@pytest.mark.parametrize("case", [
    "scope_do_not_sell", "scope_all", "scope_erased_after_ingest", "do_not_email",
    "do_not_resolve", "agent_origin", "abuse", "non_person_provider",
])
async def test_exclusion_matrix(test_db, cw, case):
    from apps.api.models.suppression import SuppressionEntry
    from apps.api.services.closed_won_seed import build_seed, ingest_deals
    from apps.api.services.crm.base import ClosedWonDeal
    from apps.api.services.pii_crypto import email_hash

    site_id = cw["site_id"]
    email = f"{case}@x.example"
    kw: dict = {}
    if case == "do_not_email":
        kw = {"do_not_email": True}
    elif case == "agent_origin":
        kw = {"source_agent_visit_id": "agent-visit-1"}
    elif case == "abuse":
        kw = {"is_abuse_flagged": True}
    provider = "hunter" if case == "non_person_provider" else "form_capture"
    await _identified(test_db, site_id, f"v-{case}", email, provider=provider,
                      dnr=(case == "do_not_resolve"), **kw)
    await test_db.commit()
    await ingest_deals(test_db, site_id, [
        ClosedWonDeal("d", email), ClosedWonDeal("d", "unmatched-ok@x.example")
    ], source="crm")
    scope = {"scope_do_not_sell": "do_not_sell", "scope_all": "all",
             "scope_erased_after_ingest": "erased"}.get(case)
    if scope:
        test_db.add(SuppressionEntry(email_hash=email_hash(email), scope=scope))
        await test_db.commit()
    build = await build_seed(test_db, site_id)
    emails = [r.email for r in build.rows]
    assert email not in emails, case
    assert "unmatched-ok@x.example" in emails  # UD6: unmatched CRM row still seeded
    assert build.excluded == 1


async def test_exclusion_company_module_absent_is_noop(test_db, cw):
    """N4: the sibling company-exclusion module is not on this branch — guarded no-op."""
    import importlib.util

    from apps.api.services.closed_won_seed import _company_excluded_domains

    assert importlib.util.find_spec("apps.api.services.company_exclusion") is None
    assert await _company_excluded_domains(test_db, cw["site_id"], {"rival.example"}) == set()


async def test_needs_reconnect_surfaces_in_seed_summary(test_db, test_client, cw, owner):
    from apps.api.models.crm_connection import CrmConnection
    from apps.api.services.closed_won_seed import NEEDS_RECONNECT_ERROR, poll_connection
    from apps.api.config import settings

    conn = (await test_db.execute(select(CrmConnection).where(
        CrmConnection.site_id == cw["site_id"], CrmConnection.provider == "hubspot"))).scalar_one()
    conn.scopes = ["crm.objects.contacts.read"]
    await test_db.commit()
    settings.mock_external_apis = False
    try:
        assert (await poll_connection(test_db, conn)) == {"needs_reconnect": True}
    finally:
        settings.mock_external_apis = True
    assert conn.last_error == NEEDS_RECONNECT_ERROR
    body = (await test_client.get(f"/api/v1/ads/{cw['site_id']}/closed-won/seed")).json()
    assert body["needs_reconnect"] is True
    assert (await test_db.scalar(select(func.count()).select_from(CrmConnection))) >= 2
