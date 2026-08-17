"""Integration tests for the outcomes report + campaign stats conversion fields.

Requires: PostgreSQL running locally (via docker-compose).
"""

import uuid as uuidlib
from datetime import datetime, timedelta

import pytest
import pytest_asyncio

pytestmark = pytest.mark.integration


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "Report Tester"},
    )
    if resp.status_code != 200:
        resp = await test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "testpass123"}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def report_setup(test_client, test_db):
    """Owner + site + 2 goals + 1 campaign (4 sent / 2 opened / 1 clicked) +
    3 in-window conversions (2 attributed by one visitor, 1 organic) + 1 old."""
    from sqlalchemy import select
    from apps.api.models.campaign import Campaign, CampaignTouchpoint
    from apps.api.models.outcome import Conversion, ConversionGoal
    from apps.api.models.site import Site
    from apps.api.models.user import User

    email = f"report-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()

    site_id = f"report_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=site_id, user_id=user.id, name="Report Site", url="https://r.example.com"))

    goal = ConversionGoal(
        id=uuidlib.uuid4(), site_id=site_id, name="Signup",
        goal_type="url_match", match_type="exact", pattern="/welcome",
        value_cents=1000, repeatable=True,
    )
    empty_goal = ConversionGoal(
        id=uuidlib.uuid4(), site_id=site_id, name="Untouched",
        goal_type="url_match", match_type="exact", pattern="/never",
    )
    test_db.add_all([goal, empty_goal])

    campaign = Campaign(
        id=uuidlib.uuid4(), site_id=site_id, name="Launch Blast",
        campaign_type="email", status="active", plan={},
    )
    test_db.add(campaign)
    await test_db.flush()

    now = datetime.utcnow()
    sent_at = now - timedelta(days=2)
    tp_ids = []
    for i in range(4):
        tp = CampaignTouchpoint(
            id=uuidlib.uuid4(), campaign_id=campaign.id, visitor_id=f"rv-{i}",
            channel="email", touchpoint_order=1, status="sent",
            content={"subject": "hi"}, sent_at=sent_at,
            opened_at=sent_at + timedelta(hours=1) if i < 2 else None,
            clicked_at=sent_at + timedelta(hours=2) if i < 1 else None,
        )
        tp_ids.append(tp.id)
        test_db.add(tp)

    def _conv(visitor, attributed, value, occurred, suffix):
        return Conversion(
            id=uuidlib.uuid4(), site_id=site_id, goal_id=goal.id, visitor_id=visitor,
            touchpoint_id=tp_ids[0] if attributed else None,
            campaign_id=campaign.id if attributed else None,
            channel="email" if attributed else None,
            attribution="campaign" if attributed else "organic",
            matched_by="click_link" if attributed else None,
            source="url_match", value_cents=value,
            dedupe_key=f"{goal.id}:{visitor}:{suffix}", occurred_at=occurred,
        )

    test_db.add_all([
        _conv("buyer-1", True, 1000, now - timedelta(days=1), "a"),
        _conv("buyer-1", True, 1000, now - timedelta(hours=20), "b"),  # same person, repeat
        _conv("stranger", False, 0, now - timedelta(days=1), "c"),
        _conv("ancient", False, 0, now - timedelta(days=90), "d"),  # outside 30d window
    ])
    await test_db.commit()
    return {"token": token, "site_id": site_id, "campaign_id": str(campaign.id)}


class TestOutcomesReport:
    @pytest.mark.asyncio
    async def test_totals_and_split(self, test_client, report_setup):
        sid, token = report_setup["site_id"], report_setup["token"]
        resp = await test_client.get(
            f"/api/v1/outcomes/{sid}/report?days=30", headers=_auth(token)
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["days"] == 30
        assert body["totals"] == {
            "conversions": 3,
            "attributed": 2,
            "organic": 1,
            "revenue_cents": 2000,
            "attributed_revenue_cents": 2000,
        }

    @pytest.mark.asyncio
    async def test_campaign_funnel_distinct_visitors(self, test_client, report_setup):
        sid, token = report_setup["site_id"], report_setup["token"]
        body = (
            await test_client.get(f"/api/v1/outcomes/{sid}/report?days=30", headers=_auth(token))
        ).json()
        assert len(body["campaigns"]) == 1
        row = body["campaigns"][0]
        assert row["campaign_id"] == report_setup["campaign_id"]
        assert row["name"] == "Launch Blast"
        assert (row["sent"], row["opened"], row["clicked"]) == (4, 2, 1)
        assert row["converted"] == 1  # buyer-1 counted once despite 2 conversions
        assert row["conversion_rate"] == 0.25
        assert row["revenue_cents"] == 2000

    @pytest.mark.asyncio
    async def test_goals_include_zero_conversion_goal(self, test_client, report_setup):
        sid, token = report_setup["site_id"], report_setup["token"]
        body = (
            await test_client.get(f"/api/v1/outcomes/{sid}/report?days=30", headers=_auth(token))
        ).json()
        by_name = {g["name"]: g for g in body["goals"]}
        assert by_name["Signup"]["conversions"] == 3
        assert by_name["Signup"]["attributed"] == 2
        assert by_name["Signup"]["revenue_cents"] == 2000
        assert by_name["Untouched"] == {
            "goal_id": by_name["Untouched"]["goal_id"],
            "name": "Untouched",
            "goal_type": "url_match",
            "enabled": True,
            "conversions": 0,
            "attributed": 0,
            "revenue_cents": 0,
        }

    @pytest.mark.asyncio
    async def test_window_widens_with_days(self, test_client, report_setup):
        sid, token = report_setup["site_id"], report_setup["token"]
        body = (
            await test_client.get(f"/api/v1/outcomes/{sid}/report?days=365", headers=_auth(token))
        ).json()
        assert body["totals"]["conversions"] == 4  # the 90-day-old one now counts

    @pytest.mark.asyncio
    async def test_days_validation_and_foreign_user(self, test_client, report_setup):
        sid, token = report_setup["site_id"], report_setup["token"]
        resp = await test_client.get(f"/api/v1/outcomes/{sid}/report?days=0", headers=_auth(token))
        assert resp.status_code == 422

        other = await _signup(test_client, f"other-{uuidlib.uuid4().hex[:8]}@test.com")
        resp = await test_client.get(f"/api/v1/outcomes/{sid}/report", headers=_auth(other))
        assert resp.status_code == 404


class TestFunnelPredicateRefactorRegression:
    """AC-13: /outcomes still counts EVERY channel after the campaign_stats
    refactor (marketing-claims-gap Phase 3).

    /outcomes has never filtered on channel and must not start. Without a
    non-email row present, a channel filter leaking into this path would be
    invisible and the "values unchanged" assertions above would pass vacuously.

    The social touchpoint is constructed DIRECTLY via the ORM: no application
    path emits one (campaign_sender hardcodes channel="email"), and the send
    path is read-only in this phase — a synthetic row is the only way to make
    this assertion real.
    """

    @pytest.mark.asyncio
    async def test_social_touchpoints_are_counted_by_outcomes(
        self, test_client, test_db, report_setup
    ):
        from apps.api.models.campaign import CampaignTouchpoint

        sid, token = report_setup["site_id"], report_setup["token"]
        url = f"/api/v1/outcomes/{sid}/report?days=30"
        before = (await test_client.get(url, headers=_auth(token))).json()
        row_before = before["campaigns"][0]
        assert (row_before["sent"], row_before["opened"], row_before["clicked"]) == (
            4,
            2,
            1,
        )

        sent_at = datetime.utcnow() - timedelta(days=2)
        test_db.add(
            CampaignTouchpoint(
                id=uuidlib.uuid4(),
                campaign_id=uuidlib.UUID(report_setup["campaign_id"]),
                visitor_id="rv-social",
                channel="social_reply",
                touchpoint_order=2,
                status="sent",
                content={},
                sent_at=sent_at,
                opened_at=sent_at + timedelta(hours=1),
                clicked_at=sent_at + timedelta(hours=2),
            )
        )
        await test_db.commit()

        after = (await test_client.get(url, headers=_auth(token))).json()
        row_after = after["campaigns"][0]
        # Every counter moves by exactly one — no channel filter leaked in.
        assert (row_after["sent"], row_after["opened"], row_after["clicked"]) == (
            5,
            3,
            2,
        )

    @pytest.mark.asyncio
    async def test_report_carries_the_open_rate_caveat_and_whats_working(
        self, test_client, report_setup
    ):
        sid, token = report_setup["site_id"], report_setup["token"]
        body = (
            await test_client.get(
                f"/api/v1/outcomes/{sid}/report?days=30", headers=_auth(token)
            )
        ).json()
        assert "Apple Mail Privacy Protection" in (body["open_rate_caveat"] or "")
        labels = {r["kind"] for r in body["whats_working"]}
        assert "campaign" in labels
        # Flag OFF by default -> no benchmark block, and the report is otherwise
        # byte-identical to before this phase.
        assert body["benchmark"] is None


class TestCampaignStatsConversions:
    @pytest.mark.asyncio
    async def test_stats_include_converted_and_revenue(self, test_client, report_setup):
        sid, token = report_setup["site_id"], report_setup["token"]
        cid = report_setup["campaign_id"]
        resp = await test_client.get(
            f"/api/v1/campaigns/{sid}/{cid}/stats", headers=_auth(token)
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["sent"] == 4
        assert body["converted"] == 1
        assert body["conversion_rate"] == 0.25
        assert body["revenue_cents"] == 2000
