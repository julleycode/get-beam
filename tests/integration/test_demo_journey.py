"""Integration test for POST /api/v1/demo/journey.

Sample-data onboarding sends users to getbeam.fyi (which runs the pixel),
then replays the pages they browsed by matching their browser fingerprint.
This verifies the fingerprint match + the duration merge (time_on_page rows
are separate from pageview rows and keyed by url).
"""

from datetime import datetime, timedelta

import pytest

from apps.api.models.event import Event
from apps.api.models.visitor import Visitor

FP = "fp2_abc123def456"


async def _seed(db) -> None:
    now = datetime.utcnow()
    db.add(
        Visitor(
            site_id="beam_getbeam_fyi",
            visitor_id="vis_journey_1",
            first_seen=now - timedelta(minutes=5),
            last_seen=now,
            fingerprint=FP,
        )
    )
    rows = [
        # pageviews carry path/title, seconds=0
        Event(site_id="beam_getbeam_fyi", visitor_id="vis_journey_1", event_type="pageview",
              url="https://getbeam.fyi/", page_path="/", page_title="home",
              created_at=now - timedelta(minutes=4)),
        Event(site_id="beam_getbeam_fyi", visitor_id="vis_journey_1", event_type="pageview",
              url="https://getbeam.fyi/pricing", page_path="/pricing", page_title="pricing",
              created_at=now - timedelta(minutes=3)),
        # duration lives in separate time_on_page rows keyed by url; dup → max wins
        Event(site_id="beam_getbeam_fyi", visitor_id="vis_journey_1", event_type="time_on_page",
              url="https://getbeam.fyi/", time_on_page=5, created_at=now - timedelta(minutes=3, seconds=30)),
        Event(site_id="beam_getbeam_fyi", visitor_id="vis_journey_1", event_type="time_on_page",
              url="https://getbeam.fyi/", time_on_page=12, created_at=now - timedelta(minutes=3, seconds=10)),
        Event(site_id="beam_getbeam_fyi", visitor_id="vis_journey_1", event_type="time_on_page",
              url="https://getbeam.fyi/pricing", time_on_page=30, created_at=now - timedelta(minutes=2)),
    ]
    for r in rows:
        db.add(r)
    await db.commit()


@pytest.mark.asyncio
async def test_journey_returns_pages_with_merged_seconds(test_db, test_client):
    await _seed(test_db)
    resp = await test_client.post("/api/v1/demo/journey", json={"fingerprint": FP})
    assert resp.status_code == 200
    data = resp.json()
    assert data["matched"] is True
    paths = [(p["path"], p["seconds"]) for p in data["pages"]]
    # pageview order preserved; seconds merged from time_on_page rows (max on dup)
    assert paths == [("/", 12), ("/pricing", 30)]


@pytest.mark.asyncio
async def test_journey_rejects_non_fingerprint(test_client):
    resp = await test_client.post("/api/v1/demo/journey", json={"fingerprint": "garbage"})
    assert resp.status_code == 200
    assert resp.json() == {"matched": False, "pages": []}


@pytest.mark.asyncio
async def test_journey_no_match_when_fingerprint_unknown(test_client):
    resp = await test_client.post("/api/v1/demo/journey", json={"fingerprint": "fp2_nonexistent"})
    assert resp.status_code == 200
    assert resp.json() == {"matched": False, "pages": []}
