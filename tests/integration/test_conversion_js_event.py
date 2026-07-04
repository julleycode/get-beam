"""Integration tests: beamConvert() conversion events through ingest.

Requires: PostgreSQL + Redis running locally (via docker-compose).
"""

import json
import uuid as uuidlib
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

_BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

pytestmark = pytest.mark.integration


def _conversion_event(goal: str, value: float | None = None, event_id: str | None = None) -> dict:
    evt: dict = {
        "type": "conversion",
        "goal": goal,
        "event_id": event_id or uuidlib.uuid4().hex,
        "url": "https://js.example.com/checkout/done",
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    if value is not None:
        evt["value"] = value
    return evt


async def _ingest(test_client, site_id: str, visitor_id: str, events: list[dict]):
    resp = await test_client.post(
        "/api/v1/events/ingest",
        content=json.dumps({"site_id": site_id, "visitor_id": visitor_id, "events": events}),
        headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA},
    )
    assert resp.status_code == 204, resp.text
    return resp


@pytest_asyncio.fixture
async def js_site(test_db):
    from apps.api.models.site import Site
    from apps.api.models.user import User

    user = User(email=f"js-{uuidlib.uuid4().hex[:8]}@test.com", full_name="JS Tester")
    test_db.add(user)
    await test_db.flush()

    site_id = f"js_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=site_id, user_id=user.id, name="JS Site", url="https://js.example.com"))
    await test_db.commit()
    return site_id


async def _add_goal(test_db, site_id: str, **overrides):
    from apps.api.models.outcome import ConversionGoal

    goal = ConversionGoal(
        id=uuidlib.uuid4(),
        site_id=site_id,
        name=overrides.pop("name", "Purchase"),
        goal_type=overrides.pop("goal_type", "js_event"),
        match_type=overrides.pop("match_type", "contains"),
        pattern=overrides.pop("pattern", ""),
        **overrides,
    )
    test_db.add(goal)
    await test_db.commit()
    return goal


async def _conversions(test_db, site_id: str):
    from apps.api.models.outcome import Conversion

    return (
        (await test_db.execute(select(Conversion).where(Conversion.site_id == site_id)))
        .scalars()
        .all()
    )


class TestJsEventConversions:
    @pytest.mark.asyncio
    async def test_matches_by_name_case_insensitive_with_value(self, test_client, test_db, js_site):
        await _add_goal(test_db, js_site, name="Purchase", value_cents=5000)
        await _ingest(test_client, js_site, "js-v1", [_conversion_event("purchase", value=12.34)])
        rows = await _conversions(test_db, js_site)
        assert len(rows) == 1
        assert rows[0].source == "js_event"
        assert rows[0].value_cents == 1234  # explicit value beats goal default
        assert rows[0].attribution == "organic"

    @pytest.mark.asyncio
    async def test_value_absent_falls_back_to_goal_default(self, test_client, test_db, js_site):
        await _add_goal(test_db, js_site, name="Signup Paid", value_cents=9900)
        await _ingest(test_client, js_site, "js-v2", [_conversion_event("Signup Paid")])
        rows = await _conversions(test_db, js_site)
        assert len(rows) == 1
        assert rows[0].value_cents == 9900

    @pytest.mark.asyncio
    async def test_unknown_and_disabled_goals_record_nothing(self, test_client, test_db, js_site):
        await _add_goal(test_db, js_site, name="Disabled", enabled=False)
        await _ingest(
            test_client, js_site, "js-v3",
            [_conversion_event("Disabled"), _conversion_event("Never Defined")],
        )
        assert await _conversions(test_db, js_site) == []

    @pytest.mark.asyncio
    async def test_repeatable_same_event_id_dedupes(self, test_client, test_db, js_site):
        await _add_goal(test_db, js_site, name="Order", repeatable=True)
        evt = _conversion_event("Order", value=10, event_id="order-777")
        await _ingest(test_client, js_site, "js-v4", [evt])
        await _ingest(test_client, js_site, "js-v4", [dict(evt)])  # webhook-style retry
        rows = await _conversions(test_db, js_site)
        assert len(rows) == 1

        # Different event_id → a second, separate conversion.
        await _ingest(
            test_client, js_site, "js-v4",
            [_conversion_event("Order", value=20, event_id="order-778")],
        )
        assert len(await _conversions(test_db, js_site)) == 2

    @pytest.mark.asyncio
    async def test_url_match_goal_can_also_take_js_values(self, test_client, test_db, js_site):
        """beamConvert may target any enabled goal by name, not only js_event ones."""
        await _add_goal(
            test_db, js_site, name="Thanks Page",
            goal_type="url_match", match_type="exact", pattern="/thanks",
        )
        await _ingest(
            test_client, js_site, "js-v5", [_conversion_event("thanks page", value=5)]
        )
        rows = await _conversions(test_db, js_site)
        assert len(rows) == 1
        assert rows[0].source == "js_event"
        assert rows[0].value_cents == 500
