"""G2 / G6 — per-account rollup API against real Postgres (flag ON).

Requires PG + Redis (docker-compose) with DATABASE_URL pinned to localhost.
"""

import os
import time
import uuid as uuidlib
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration

NOW = datetime.now(timezone.utc).replace(tzinfo=None)
OLD = NOW - timedelta(days=40)
_BANNED_KEYS = {"email", "full_name", "phone", "ip_address", "visitor_id"}


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "Acct Tester"},
    )
    if resp.status_code != 200:
        resp = await test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "testpass123"}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


def _v(site_id, vid, domain="acme.com", **kw):
    from apps.api.models.visitor import Visitor

    base = dict(
        site_id=site_id, visitor_id=vid, first_seen=kw.get("last_seen", NOW),
        last_seen=NOW, company_domain=domain, total_sessions=1, total_pageviews=1,
        pages_visited=[], identity_status="anonymous",
    )
    base.update(kw)
    return Visitor(**base)


@pytest.fixture
def flag_on(monkeypatch):
    from apps.api.config import settings

    monkeypatch.setattr(settings, "account_rollup_enabled", True)


@pytest_asyncio.fixture
async def acct(test_client, test_db):
    from apps.api.models.campaign import Campaign, CampaignTouchpoint
    from apps.api.models.outcome import CampaignClick, Conversion, ConversionGoal
    from apps.api.models.site import Site
    from apps.api.models.user import User

    email = f"acct-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()
    sid = f"acct_a_{uuidlib.uuid4().hex[:8]}"
    sid_b = f"acct_b_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=sid, user_id=user.id, name="A", url="https://a.example"))
    test_db.add(Site(site_id=sid_b, user_id=user.id, name="B", url="https://b.example"))
    await test_db.flush()

    test_db.add_all([
        _v(sid, "v1", identity_status="identified", total_sessions=2, total_pageviews=5,
           pages_visited=["https://acme.com/pricing?x=1"]),
        _v(sid, "v2", is_bot_suspect=True, pages_visited=["https://acme.com/pricing-blog"]),
        _v(sid, "p", is_imported_contact=True, total_sessions=0, total_pageviews=0),
        _v(sid, "c", identity_status="merged", canonical_visitor_id="p",
           total_sessions=3, total_pageviews=4),
        _v(sid, "agent", is_agent_derived=True, total_sessions=10),
        _v(sid, "abuse", is_abuse_flagged=True, total_sessions=10),
        _v(sid, "old", last_seen=OLD, first_seen=OLD),
        _v(sid, "free", domain="gmail.com"),
        _v(sid, "nodom", domain=None),
        # Cross-tenant: same visitor_id on site B must never bleed into A.
        _v(sid_b, "v1", total_sessions=100, total_pageviews=100),
    ])
    camp = Campaign(site_id=sid, name="Spring", status="active", plan={})
    camp_b = Campaign(site_id=sid_b, name="B camp", status="active", plan={})
    test_db.add_all([camp, camp_b])
    await test_db.flush()

    def tp(c, vid, status="sent", sent_at=NOW):
        return CampaignTouchpoint(campaign_id=c.id, visitor_id=vid, channel="email",
                                  touchpoint_order=1, status=status, content={}, sent_at=sent_at)

    tp_c, tp_v1, tp_old, tp_b = tp(camp, "c"), tp(camp, "v1", status="pending"), \
        tp(camp, "old", sent_at=OLD), tp(camp_b, "v1")
    test_db.add_all([tp_c, tp_v1, tp_old, tp_b])
    await test_db.flush()
    test_db.add_all([
        CampaignClick(touchpoint_id=tp_c.id, campaign_id=camp.id, site_id=sid,
                      visitor_id="c", clicked_at=NOW),
        CampaignClick(touchpoint_id=tp_old.id, campaign_id=camp.id, site_id=sid,
                      visitor_id="old", clicked_at=OLD),
        CampaignClick(touchpoint_id=tp_b.id, campaign_id=camp_b.id, site_id=sid_b,
                      visitor_id="v1", clicked_at=NOW),
    ])
    demo = ConversionGoal(site_id=sid, name="Demo booked", pattern="/thanks")
    other = ConversionGoal(site_id=sid, name="Signup", pattern="/welcome")
    goal_b = ConversionGoal(site_id=sid_b, name="Demo booked", pattern="/thanks")
    test_db.add_all([demo, other, goal_b])
    await test_db.flush()

    def conv(site, goal, vid, at=NOW, campaign_id=None):
        return Conversion(site_id=site, goal_id=goal.id, visitor_id=vid, occurred_at=at,
                          dedupe_key=uuidlib.uuid4().hex, campaign_id=campaign_id)

    test_db.add_all([
        conv(sid, demo, "c", campaign_id=camp.id),
        conv(sid, other, "v1"),
        conv(sid, demo, "old", at=OLD),
        conv(sid_b, goal_b, "v1"),
    ])
    await test_db.commit()
    return {"token": token, "sid": sid, "sid_b": sid_b, "camp": str(camp.id)}


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


class TestGates:
    @pytest.mark.asyncio
    async def test_flag_off_404(self, test_client, acct):
        r = await test_client.get(f"/api/v1/accounts/{acct['sid']}", headers=_auth(acct["token"]))
        assert r.status_code == 404
        r = await test_client.get(f"/api/v1/accounts/{acct['sid']}/acme.com",
                                  headers=_auth(acct["token"]))
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_foreign_site_and_unknown_domain_404(self, test_client, acct, flag_on):
        other = await _signup(test_client, f"acct-o-{uuidlib.uuid4().hex[:8]}@test.com")
        r = await test_client.get(f"/api/v1/accounts/{acct['sid']}", headers=_auth(other))
        assert r.status_code == 404
        r = await test_client.get(f"/api/v1/accounts/{acct['sid']}/nope.example",
                                  headers=_auth(acct["token"]))
        assert r.status_code == 404
        r = await test_client.get(f"/api/v1/accounts/{acct['sid']}/gmail.com",
                                  headers=_auth(acct["token"]))
        assert r.status_code == 404


class TestCounts:
    @pytest.mark.asyncio
    async def test_exact_counts_flag_on(self, test_client, acct, flag_on):
        r = await test_client.get(f"/api/v1/accounts/{acct['sid']}",
                                  params={"days": 30, "sort": "visitors"},
                                  headers=_auth(acct["token"]))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 1
        row = body["accounts"][0]
        assert row["domain"] == "acme.com"
        # v1, v2 (bot-suspect counted), p (+ merged child c folded) = 3 people.
        assert row["visitors"] == 3
        assert row["identified_people"] == 2  # v1 + p via merged child
        assert row["sessions"] == 6  # 2 + 1 + 0 + 3 (agent/abuse/old excluded)
        assert row["pageviews"] == 10
        assert row["pricing_visitors"] == 1  # full URL counted, /pricing-blog not
        assert row["touched"] == 1  # sent to c; pending + 40d-old + site-B excluded
        assert row["clicks"] == 1
        assert row["conversions"] == 2
        assert row["demo_bookings"] == 1
        assert row["replies"] is None and row["pipeline_value_cents"] is None
        assert len(body["known_gaps"]) == 2

    @pytest.mark.asyncio
    async def test_days_boundary_includes_old_activity(self, test_client, acct, flag_on):
        r = await test_client.get(f"/api/v1/accounts/{acct['sid']}", params={"days": 60},
                                  headers=_auth(acct["token"]))
        row = r.json()["accounts"][0]
        assert row["visitors"] == 4  # + old
        assert row["touched"] == 2 and row["clicks"] == 2
        assert row["conversions"] == 3 and row["demo_bookings"] == 2

    @pytest.mark.asyncio
    async def test_cross_tenant_zero_bleed(self, test_client, acct, flag_on):
        r = await test_client.get(f"/api/v1/accounts/{acct['sid_b']}",
                                  headers=_auth(acct["token"]))
        row = r.json()["accounts"][0]
        assert (row["visitors"], row["sessions"], row["touched"], row["clicks"],
                row["conversions"]) == (1, 100, 1, 1, 1)

    @pytest.mark.asyncio
    async def test_detail_with_campaigns_and_no_pii(self, test_client, acct, flag_on):
        r = await test_client.get(f"/api/v1/accounts/{acct['sid']}/ACME.com",
                                  headers=_auth(acct["token"]))
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["visitors"] == 3 and d["clicks"] == 1
        assert d["campaigns"] == [{"campaign_id": acct["camp"], "name": "Spring",
                                   "touched": 1, "clicks": 1, "conversions": 1}]
        r2 = await test_client.get(f"/api/v1/accounts/{acct['sid']}",
                                   headers=_auth(acct["token"]))
        for payload in (d, r2.json()):
            assert not _BANNED_KEYS & set(_keys(payload))

    @pytest.mark.asyncio
    async def test_bad_params_422(self, test_client, acct, flag_on):
        r = await test_client.get(f"/api/v1/accounts/{acct['sid']}",
                                  params={"sort": "email"}, headers=_auth(acct["token"]))
        assert r.status_code == 422


@pytest_asyncio.fixture
async def seed_10k(test_db):
    """10,000 visitors over 500 domains, plus clicks + conversions."""
    from sqlalchemy import insert

    from apps.api.models.campaign import Campaign, CampaignTouchpoint
    from apps.api.models.outcome import CampaignClick, Conversion, ConversionGoal
    from apps.api.models.site import Site
    from apps.api.models.user import User
    from apps.api.models.visitor import Visitor

    user = User(email=f"perf-{uuidlib.uuid4().hex[:8]}@test.com", full_name="Perf")
    test_db.add(user)
    await test_db.flush()
    sid = f"perf_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=sid, user_id=user.id, name="P", url="https://p.example"))
    camp = Campaign(site_id=sid, name="perf", status="active", plan={})
    goal = ConversionGoal(site_id=sid, name="Demo booked", pattern="/thanks")
    test_db.add_all([camp, goal])
    await test_db.flush()
    rows = [
        dict(site_id=sid, visitor_id=f"v{i}", first_seen=NOW, last_seen=NOW,
             company_domain=f"d{i % 500}.com", total_sessions=2, total_pageviews=4,
             pages_visited=[f"https://d{i % 500}.com/pricing?x={i}", "https://x.com/a"],
             identity_status="identified" if i % 3 == 0 else "anonymous")
        for i in range(10_000)
    ]
    await test_db.execute(insert(Visitor), rows)
    tps = [dict(id=uuidlib.uuid4(), campaign_id=camp.id, visitor_id=f"v{i}", channel="email",
                touchpoint_order=1, status="sent", content={}, sent_at=NOW)
           for i in range(0, 10_000, 5)]
    await test_db.execute(insert(CampaignTouchpoint), tps)
    await test_db.execute(insert(CampaignClick), [
        dict(touchpoint_id=t["id"], campaign_id=camp.id, site_id=sid,
             visitor_id=t["visitor_id"], clicked_at=NOW) for t in tps[::2]])
    await test_db.execute(insert(Conversion), [
        dict(site_id=sid, goal_id=goal.id, visitor_id=t["visitor_id"], occurred_at=NOW,
             dedupe_key=uuidlib.uuid4().hex) for t in tps[::4]])
    await test_db.commit()
    # Prod tables are autovacuum-analyzed; freshly bulk-loaded test tables are
    # not, and stale rows=1 estimates force nested-loop plans that prod never sees.
    from sqlalchemy import text

    for table in ("visitors", "campaign_touchpoints", "campaign_clicks", "conversions",
                  "campaigns", "conversion_goals", "companies"):
        await test_db.execute(text(f"ANALYZE {table}"))
    await test_db.commit()
    return sid


@pytest.mark.perf
@pytest.mark.skipif(os.environ.get("ACCOUNTS_PERF") != "1", reason="set ACCOUNTS_PERF=1")
@pytest.mark.asyncio
async def test_accounts_perf(test_db, seed_10k):
    from sqlalchemy import text

    from apps.api.services.account_rollup import _rollup, _since, list_accounts

    q, cols, vagg = _rollup(seed_10k, _since(30))
    compiled = q.order_by(cols["visitors"].desc()).limit(25).compile(
        compile_kwargs={"literal_binds": True})
    plan = (await test_db.execute(text(f"EXPLAIN (ANALYZE, BUFFERS) {compiled}"))).scalars().all()
    print("\nEXPLAIN (ANALYZE, BUFFERS):\n" + "\n".join(plan[:3] + plan[-3:]))
    times = []
    for i in range(20):
        t0 = time.perf_counter()
        res = await list_accounts(test_db, seed_10k, 30, "visitors" if i % 2 else "last_seen", 1, 25)
        times.append((time.perf_counter() - t0) * 1000)
    assert res.total == 500
    p95 = sorted(times)[18]
    print(f"\nACCOUNTS_PERF p95={p95:.1f}ms median={sorted(times)[10]:.1f}ms")
    assert p95 < 500
