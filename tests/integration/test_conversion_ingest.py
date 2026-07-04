"""Integration tests: pixel ingest → conversion goal matching + attribution.

Requires: PostgreSQL + Redis running locally (via docker-compose).
"""

import json
import uuid as uuidlib
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

# Realistic browser UA to avoid bot filter (is_bot returns True for empty UA)
_BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

pytestmark = pytest.mark.integration


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _pageview(url: str, path: str, ts: datetime | None = None) -> dict:
    return {
        "type": "pageview",
        "event_id": uuidlib.uuid4().hex,
        "url": url,
        "page_path": path,
        "ts": (ts or _now_utc()).isoformat(),
    }


async def _ingest(test_client, site_id: str, visitor_id: str, events: list[dict]):
    resp = await test_client.post(
        "/api/v1/events/ingest",
        content=json.dumps({"site_id": site_id, "visitor_id": visitor_id, "events": events}),
        headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA},
    )
    assert resp.status_code == 204, resp.text
    return resp


@pytest_asyncio.fixture
async def conv_site(test_db):
    """Site + owner, plus a helper to add goals/campaigns via ORM."""
    from apps.api.models.site import Site
    from apps.api.models.user import User

    user = User(email=f"conv-{uuidlib.uuid4().hex[:8]}@test.com", full_name="Conv Tester")
    test_db.add(user)
    await test_db.flush()

    site_id = f"conv_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=site_id, user_id=user.id, name="Conv Site", url="https://conv.example.com"))
    await test_db.commit()
    return site_id


async def _add_goal(test_db, site_id: str, **overrides):
    from apps.api.models.outcome import ConversionGoal

    goal = ConversionGoal(
        id=uuidlib.uuid4(),
        site_id=site_id,
        name=overrides.pop("name", f"Goal {uuidlib.uuid4().hex[:6]}"),
        goal_type="url_match",
        match_type=overrides.pop("match_type", "exact"),
        pattern=overrides.pop("pattern", "/thanks"),
        **overrides,
    )
    test_db.add(goal)
    await test_db.commit()
    return goal


async def _add_campaign_touchpoint(test_db, site_id: str, visitor_id: str, **tp_overrides):
    """Campaign + one sent email touchpoint targeting ``visitor_id``."""
    from apps.api.models.campaign import Campaign, CampaignTouchpoint

    campaign = Campaign(
        id=uuidlib.uuid4(), site_id=site_id, name="Test Campaign",
        campaign_type="email", status="active", plan={},
    )
    test_db.add(campaign)
    await test_db.flush()

    tp = CampaignTouchpoint(
        id=uuidlib.uuid4(),
        campaign_id=campaign.id,
        visitor_id=visitor_id,
        channel="email",
        touchpoint_order=1,
        status="sent",
        content={"subject": "hi"},
        sent_at=datetime.utcnow() - timedelta(days=1),
        **tp_overrides,
    )
    test_db.add(tp)
    await test_db.commit()
    return campaign, tp


async def _conversions(test_db, site_id: str):
    from apps.api.models.outcome import Conversion

    return (
        (await test_db.execute(select(Conversion).where(Conversion.site_id == site_id)))
        .scalars()
        .all()
    )


class TestOrganicConversions:
    @pytest.mark.asyncio
    async def test_matching_pageview_records_organic(self, test_client, test_db, conv_site):
        await _add_goal(test_db, conv_site, pattern="/thanks", match_type="exact")
        await _ingest(
            test_client, conv_site, "stranger-1",
            [_pageview("https://conv.example.com/thanks?utm_source=x", "/thanks")],
        )
        rows = await _conversions(test_db, conv_site)
        assert len(rows) == 1
        assert rows[0].attribution == "organic"
        assert rows[0].campaign_id is None
        assert rows[0].matched_by is None
        assert rows[0].source == "url_match"

    @pytest.mark.asyncio
    async def test_non_matching_and_disabled_goals_record_nothing(
        self, test_client, test_db, conv_site
    ):
        await _add_goal(test_db, conv_site, pattern="/thanks", match_type="exact")
        await _add_goal(
            test_db, conv_site, name="Disabled", pattern="/pricing",
            match_type="exact", enabled=False,
        )
        await _ingest(
            test_client, conv_site, "stranger-2",
            [_pageview("https://conv.example.com/pricing", "/pricing")],
        )
        assert await _conversions(test_db, conv_site) == []


class TestClickLinkAttribution:
    @pytest.mark.asyncio
    async def test_tp_landing_records_click_link_for_landing_visitor(
        self, test_client, test_db, conv_site
    ):
        from apps.api.models.outcome import CampaignClick

        campaign, tp = await _add_campaign_touchpoint(test_db, conv_site, "visitor-a")

        # Visitor B (a DIFFERENT browser than the emailed visitor-a) lands with _tp.
        landing = _pageview(
            f"https://conv.example.com/pricing?_tp={tp.id}", "/pricing"
        )
        await _ingest(test_client, conv_site, "visitor-b", [landing])

        links = (
            (await test_db.execute(select(CampaignClick).where(CampaignClick.site_id == conv_site)))
            .scalars()
            .all()
        )
        assert len(links) == 1
        assert links[0].visitor_id == "visitor-b"
        assert links[0].touchpoint_id == tp.id
        assert links[0].campaign_id == campaign.id

        # Replay the exact same batch (beacon retry) — still one link row.
        await _ingest(test_client, conv_site, "visitor-b", [landing])
        links = (
            (await test_db.execute(select(CampaignClick).where(CampaignClick.site_id == conv_site)))
            .scalars()
            .all()
        )
        assert len(links) == 1

    @pytest.mark.asyncio
    async def test_conversion_after_click_attributes_to_campaign(
        self, test_client, test_db, conv_site
    ):
        campaign, tp = await _add_campaign_touchpoint(test_db, conv_site, "visitor-a")
        await _add_goal(test_db, conv_site, pattern="/thanks", match_type="exact")

        # Click landing first (non-converting page), then the conversion pageview.
        await _ingest(
            test_client, conv_site, "visitor-b",
            [_pageview(f"https://conv.example.com/pricing?_tp={tp.id}", "/pricing")],
        )
        await _ingest(
            test_client, conv_site, "visitor-b",
            [_pageview("https://conv.example.com/thanks", "/thanks")],
        )

        rows = await _conversions(test_db, conv_site)
        assert len(rows) == 1
        assert rows[0].attribution == "campaign"
        assert rows[0].matched_by == "click_link"
        assert rows[0].campaign_id == campaign.id
        assert rows[0].touchpoint_id == tp.id
        assert rows[0].channel == "email"

    @pytest.mark.asyncio
    async def test_landing_page_that_is_itself_the_goal_attributes_in_one_batch(
        self, test_client, test_db, conv_site
    ):
        """_tp link click lands DIRECTLY on the goal URL — ordering must hold."""
        campaign, tp = await _add_campaign_touchpoint(test_db, conv_site, "visitor-a")
        await _add_goal(test_db, conv_site, pattern="/offer", match_type="exact")

        await _ingest(
            test_client, conv_site, "visitor-c",
            [_pageview(f"https://conv.example.com/offer?_tp={tp.id}", "/offer")],
        )
        rows = await _conversions(test_db, conv_site)
        assert len(rows) == 1
        assert rows[0].attribution == "campaign"
        assert rows[0].matched_by == "click_link"
        assert rows[0].campaign_id == campaign.id

    @pytest.mark.asyncio
    async def test_click_older_than_window_is_organic(self, test_client, test_db, conv_site):
        from apps.api.models.outcome import CampaignClick

        campaign, tp = await _add_campaign_touchpoint(test_db, conv_site, "visitor-a")
        await _add_goal(test_db, conv_site, pattern="/thanks", match_type="exact")

        test_db.add(
            CampaignClick(
                id=uuidlib.uuid4(),
                touchpoint_id=tp.id,
                campaign_id=campaign.id,
                site_id=conv_site,
                visitor_id="visitor-old",
                clicked_at=datetime.utcnow() - timedelta(days=31),
            )
        )
        await test_db.commit()

        await _ingest(
            test_client, conv_site, "visitor-old",
            [_pageview("https://conv.example.com/thanks", "/thanks")],
        )
        rows = await _conversions(test_db, conv_site)
        assert len(rows) == 1
        assert rows[0].attribution == "organic"


class TestSameVisitorFallback:
    @pytest.mark.asyncio
    async def test_clicked_touchpoint_without_link_row_attributes(
        self, test_client, test_db, conv_site
    ):
        """Historical touchpoints (pre-campaign_clicks) still attribute same-browser."""
        campaign, tp = await _add_campaign_touchpoint(
            test_db, conv_site, "visitor-a",
            clicked_at=datetime.utcnow() - timedelta(hours=2),
        )
        await _add_goal(test_db, conv_site, pattern="/thanks", match_type="exact")

        await _ingest(
            test_client, conv_site, "visitor-a",
            [_pageview("https://conv.example.com/thanks", "/thanks")],
        )
        rows = await _conversions(test_db, conv_site)
        assert len(rows) == 1
        assert rows[0].attribution == "campaign"
        assert rows[0].matched_by == "same_visitor"
        assert rows[0].campaign_id == campaign.id

    @pytest.mark.asyncio
    async def test_unclicked_touchpoint_never_attributes(self, test_client, test_db, conv_site):
        """Send-only (or open-only) touchpoints must NOT attribute — click-gated."""
        await _add_campaign_touchpoint(
            test_db, conv_site, "visitor-a",
            opened_at=datetime.utcnow() - timedelta(hours=1),  # opened but never clicked
        )
        await _add_goal(test_db, conv_site, pattern="/thanks", match_type="exact")

        await _ingest(
            test_client, conv_site, "visitor-a",
            [_pageview("https://conv.example.com/thanks", "/thanks")],
        )
        rows = await _conversions(test_db, conv_site)
        assert len(rows) == 1
        assert rows[0].attribution == "organic"


class TestDedupe:
    @pytest.mark.asyncio
    async def test_non_repeatable_once_per_visitor(self, test_client, test_db, conv_site):
        await _add_goal(test_db, conv_site, pattern="/thanks", match_type="exact")
        for _ in range(2):
            await _ingest(
                test_client, conv_site, "dedupe-v1",
                [_pageview("https://conv.example.com/thanks", "/thanks")],
            )
        assert len(await _conversions(test_db, conv_site)) == 1

    @pytest.mark.asyncio
    async def test_repeatable_once_per_day(self, test_client, test_db, conv_site):
        await _add_goal(
            test_db, conv_site, pattern="/order", match_type="prefix", repeatable=True
        )
        day1 = datetime(2026, 7, 1, 10, tzinfo=timezone.utc)
        day2 = datetime(2026, 7, 2, 10, tzinfo=timezone.utc)
        await _ingest(
            test_client, conv_site, "dedupe-v2",
            [
                _pageview("https://conv.example.com/order/1", "/order/1", ts=day1),
                _pageview("https://conv.example.com/order/2", "/order/2", ts=day1),
                _pageview("https://conv.example.com/order/3", "/order/3", ts=day2),
            ],
        )
        rows = await _conversions(test_db, conv_site)
        assert len(rows) == 2  # day1 deduped to one, day2 is a fresh bucket


class TestIngestResilience:
    @pytest.mark.asyncio
    async def test_tracker_crash_never_blocks_ingest(
        self, test_client, test_db, conv_site, monkeypatch
    ):
        import apps.api.services.conversion_tracker as ct

        async def _boom(db, batch):  # noqa: ARG001
            raise RuntimeError("tracker exploded")

        monkeypatch.setattr(ct, "process_batch", _boom)
        resp = await _ingest(
            test_client, conv_site, "resilient-v",
            [_pageview("https://conv.example.com/thanks", "/thanks")],
        )
        assert resp.status_code == 204
