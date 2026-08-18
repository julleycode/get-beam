"""WS2 agent_sig ingest round-trip (SPEC AC-4, AC-7).

Requires: PostgreSQL + Redis running locally (via docker-compose).
Uses test_client and test_db from conftest.py which auto-create tables.

Two properties, both of which the unit tier structurally cannot prove:

  AC-4 — the value survives the whole ingest path and is readable back off the
         **Event** row. This is the leg that catches the plan's single
         highest-value correction: persisting via the ``_process_signal_events``
         fp/fp3 path would write to the **Visitor** row instead, and every other
         gate would still look green while the classifier read NULL forever.

  AC-7 — classification never causes a drop. A batch whose agent_sig screams
         "automation" still returns 204 and still gets its row written.
"""

import uuid as uuidlib

import pytest
import pytest_asyncio
from sqlalchemy import select

_BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def test_site_id(test_db):
    from apps.api.models.site import Site
    from apps.api.models.user import User

    result = await test_db.execute(select(User).where(User.email == "test-agentsig@test.com"))
    user = result.scalar_one_or_none()
    if not user:
        user = User(email="test-agentsig@test.com", full_name="Test User")
        test_db.add(user)
        await test_db.flush()

    site_id = "test_site_agent_sig"
    result = await test_db.execute(select(Site).where(Site.site_id == site_id))
    if not result.scalar_one_or_none():
        test_db.add(
            Site(
                site_id=site_id,
                user_id=user.id,
                name="Test Site",
                url="https://test-agentsig.example.com",
            )
        )
        await test_db.flush()

    await test_db.commit()
    return site_id


def _batch(site_id: str, visitor_id: str, asig: dict | None) -> dict:
    event: dict = {
        "type": "click",
        "event_id": uuidlib.uuid4().hex,
        "url": "https://test-agentsig.example.com/pricing",
        "page_path": "/pricing",
        "page_title": "Pricing",
        "user_agent": _BROWSER_UA,
        "ts": "2026-08-07T00:00:00",
    }
    if asig is not None:
        event["_asig"] = asig
    return {"site_id": site_id, "visitor_id": visitor_id, "events": [event]}


async def _event_rows(test_db, site_id: str, visitor_id: str):
    from apps.api.models.event import Event

    result = await test_db.execute(
        select(Event).where(Event.site_id == site_id, Event.visitor_id == visitor_id)
    )
    return result.scalars().all()


class TestAgentSigPersistence:
    @pytest.mark.asyncio
    async def test_agent_sig_round_trips_onto_the_event_row(
        self, test_client, test_db, test_site_id
    ):
        """AC-4: the exact object comes back off events.agent_sig, not Visitor."""
        visitor_id = "agentsig-visitor-roundtrip"
        sig = {"w": False, "h": False, "p": 0, "d": 3, "c": 5}

        resp = await test_client.post(
            "/api/v1/events/ingest",
            json=_batch(test_site_id, visitor_id, sig),
            headers={"User-Agent": _BROWSER_UA},
        )
        assert resp.status_code == 204, resp.text

        rows = await _event_rows(test_db, test_site_id, visitor_id)
        assert len(rows) == 1
        assert rows[0].agent_sig == {"w": False, "h": False, "p": 0.0, "d": 3, "c": 5}

    @pytest.mark.asyncio
    async def test_agent_indicating_session_is_stored_never_dropped(
        self, test_client, test_db, test_site_id
    ):
        """AC-7: a maximally agent-looking payload is classified, not blocked."""
        visitor_id = "agentsig-visitor-agentlike"
        sig = {"w": True, "h": True, "p": 0, "d": 9, "c": 9}

        resp = await test_client.post(
            "/api/v1/events/ingest",
            json=_batch(test_site_id, visitor_id, sig),
            headers={"User-Agent": _BROWSER_UA},
        )
        assert resp.status_code == 204, resp.text

        rows = await _event_rows(test_db, test_site_id, visitor_id)
        assert len(rows) == 1, "an agent-indicating session must still be persisted"
        assert rows[0].agent_sig["w"] is True

    @pytest.mark.asyncio
    async def test_older_pixel_without_agent_sig_still_ingests(
        self, test_client, test_db, test_site_id
    ):
        """Additive/optional: a build predating this field is unaffected."""
        visitor_id = "agentsig-visitor-legacy"

        resp = await test_client.post(
            "/api/v1/events/ingest",
            json=_batch(test_site_id, visitor_id, None),
            headers={"User-Agent": _BROWSER_UA},
        )
        assert resp.status_code == 204, resp.text

        rows = await _event_rows(test_db, test_site_id, visitor_id)
        assert len(rows) == 1
        assert rows[0].agent_sig is None

    @pytest.mark.asyncio
    async def test_hostile_agent_sig_does_not_reject_the_batch(
        self, test_client, test_db, test_site_id
    ):
        """AC-7 boundary: junk in _asig degrades to NULL, never 422s the batch."""
        visitor_id = "agentsig-visitor-hostile"

        resp = await test_client.post(
            "/api/v1/events/ingest",
            json=_batch(test_site_id, visitor_id, {"junk": "x" * 5000}),
            headers={"User-Agent": _BROWSER_UA},
        )
        assert resp.status_code == 204, resp.text

        rows = await _event_rows(test_db, test_site_id, visitor_id)
        assert len(rows) == 1, "a legitimate event must survive a malformed _asig"
        assert rows[0].agent_sig is None
