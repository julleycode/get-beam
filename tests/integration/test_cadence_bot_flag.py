"""Integration tests for the cadence bot flag (AC-4, AC-5, AC-6, AC-7, AC-10).

Requires: PostgreSQL + Redis running locally
(``docker compose -f infra/docker-compose.yml up -d postgres redis``).

Unit-level coverage for the pure detection math and the structural-isolation
AST checks lives in ``tests/unit/test_cadence_bot_flag.py``. This file proves the
DB-facing behavior: the sweep's end-to-end flag decision, the bounded-read cap,
and the three "nothing else changed" regressions (ingest, emailability,
aggregation).
"""

from datetime import datetime, timedelta
import uuid as uuidlib

import pytest
import pytest_asyncio
from sqlalchemy import select

_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
)

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def test_site_id(test_db):
    """Create a test site using the ORM and return its site_id."""
    from apps.api.models.site import Site
    from apps.api.models.user import User

    result = await test_db.execute(
        select(User).where(User.email == "test-cadence@test.com")
    )
    user = result.scalar_one_or_none()
    if not user:
        user = User(email="test-cadence@test.com", full_name="Cadence Test User")
        test_db.add(user)
        await test_db.flush()

    site_id = "test_site_cadence"
    result = await test_db.execute(select(Site).where(Site.site_id == site_id))
    if not result.scalar_one_or_none():
        test_db.add(
            Site(
                site_id=site_id,
                user_id=user.id,
                name="Cadence Test Site",
                url="https://cadence-test.example.com",
            )
        )
        await test_db.flush()

    await test_db.commit()
    return site_id


async def _seed_visitor(
    db,
    site_id: str,
    visitor_id: str,
    *,
    days: int,
    event_types_per_day: list[str],
    day_offset: int = 0,
    jitter_seconds: int = 0,
):
    """Seed one visit per day for `days` days, each with the given event types."""
    from apps.api.models.event import Event
    from apps.api.models.visitor import Visitor

    base = datetime.utcnow() - timedelta(days=days + day_offset)
    for day in range(days):
        stamp = base + timedelta(days=day, seconds=(day * jitter_seconds))
        for event_type in event_types_per_day:
            db.add(
                Event(
                    site_id=site_id,
                    visitor_id=visitor_id,
                    event_type=event_type,
                    user_agent=_BROWSER_UA,
                    created_at=stamp,
                )
            )

    db.add(
        Visitor(
            site_id=site_id,
            visitor_id=visitor_id,
            first_seen=base,
            last_seen=base + timedelta(days=days),
        )
    )
    await db.commit()


async def _run_sweep(db, monkeypatch):
    from apps.api.config import settings
    from apps.api.services.cadence_bot_flag_sweep import run_cadence_bot_flag_sweep

    monkeypatch.setattr(settings, "cadence_bot_flag_enabled", True, raising=False)
    return await run_cadence_bot_flag_sweep(db)


async def _visitor_flag(db, site_id: str, visitor_id: str) -> bool:
    from apps.api.models.visitor import Visitor

    result = await db.execute(
        select(Visitor.is_bot_suspect).where(
            Visitor.site_id == site_id, Visitor.visitor_id == visitor_id
        )
    )
    return bool(result.scalar_one())


# ─── AC-4: batch-only, ingest untouched ───


@pytest.mark.asyncio
async def test_ingest_unaffected_by_new_module(test_client, test_db, test_site_id):
    """POST /ingest behaves identically with the new module present, sweep unrun."""
    import apps.api.services.cadence_bot_flag_sweep  # noqa: F401  (import side effects)
    from apps.api.models.event import Event

    payload = {
        "site_id": test_site_id,
        "visitor_id": "cadence_ingest_probe",
        "events": [
            {
                "type": "pageview",
                "event_id": uuidlib.uuid4().hex,
                "url": "https://cadence-test.example.com/",
                "page_path": "/",
                "page_title": "Home",
                "user_agent": _BROWSER_UA,
                "ts": "2026-07-25T00:00:00",
            }
        ],
    }
    response = await test_client.post(
        "/api/v1/events/ingest", json=payload, headers={"User-Agent": _BROWSER_UA}
    )
    assert response.status_code in (200, 204)

    result = await test_db.execute(
        select(Event).where(
            Event.site_id == test_site_id, Event.visitor_id == "cadence_ingest_probe"
        )
    )
    events = list(result.scalars().all())
    assert events, "ingest must still store the event"
    # The ingest path never sets the new flag — that is the sweep's job only.
    for event in events:
        assert event.is_flagged_abuse is False


# ─── AC-5/AC-6: outreach eligibility untouched ───


@pytest.mark.asyncio
async def test_is_emailable_identity_unaffected(test_db, test_site_id):
    """A bot-suspect identity stays exactly as emailable as before."""
    import inspect

    from apps.api.models.visitor import IdentifiedVisitor
    from apps.api.services.identity_classification import is_emailable_identity

    identity = IdentifiedVisitor(
        site_id=test_site_id,
        visitor_id="cadence_emailable_probe",
        email="probe@example.com",
        resolution_provider="form_capture",
        is_bot_suspect=True,
    )
    test_db.add(identity)
    await test_db.commit()

    assert is_emailable_identity(identity.resolution_provider, None, False) is True
    # Structural guard against silent signature drift.
    assert len(inspect.signature(is_emailable_identity).parameters) == 3


# ─── AC-7: aggregates undistorted ───


@pytest.mark.asyncio
async def test_aggregation_output_unchanged(test_db, test_site_id):
    """Aggregation output for a flagged visitor is identical to unflagged."""
    from apps.api.models.visitor import Visitor
    from apps.api.services.visitor_aggregator import aggregate_visitors_for_site

    await _seed_visitor(
        test_db,
        test_site_id,
        "cadence_agg_probe",
        days=4,
        event_types_per_day=["pageview", "scroll"],
    )

    await aggregate_visitors_for_site(test_db, test_site_id)
    result = await test_db.execute(
        select(Visitor).where(
            Visitor.site_id == test_site_id, Visitor.visitor_id == "cadence_agg_probe"
        )
    )
    visitor = result.scalar_one()
    unflagged = (
        visitor.total_pageviews,
        visitor.total_sessions,
        visitor.avg_time_on_page,
        visitor.max_scroll_depth,
        visitor.intent_score,
    )

    visitor.is_bot_suspect = True
    await test_db.commit()

    await aggregate_visitors_for_site(test_db, test_site_id)
    await test_db.refresh(visitor)
    flagged = (
        visitor.total_pageviews,
        visitor.total_sessions,
        visitor.avg_time_on_page,
        visitor.max_scroll_depth,
        visitor.intent_score,
    )

    assert flagged == unflagged, "is_bot_suspect must not change any aggregate"
    assert visitor.is_bot_suspect is True, "aggregation must not clear the flag"


# ─── AC-10: API serialization ───


@pytest.mark.asyncio
async def test_visitor_detail_serializes_is_bot_suspect(test_db, test_site_id):
    """VisitorOut carries the new field for flagged and unflagged rows alike."""
    from apps.api.models.visitor import Visitor
    from apps.api.schemas.visitors import VisitorOut

    now = datetime.utcnow()
    flagged = Visitor(
        site_id=test_site_id,
        visitor_id="cadence_api_flagged",
        first_seen=now,
        last_seen=now,
        is_bot_suspect=True,
    )
    unflagged = Visitor(
        site_id=test_site_id,
        visitor_id="cadence_api_unflagged",
        first_seen=now,
        last_seen=now,
    )
    test_db.add_all([flagged, unflagged])
    await test_db.commit()

    assert VisitorOut.model_validate(flagged).is_bot_suspect is True
    assert VisitorOut.model_validate(unflagged).is_bot_suspect is False


# ─── End-to-end sweep behavior ───


@pytest.mark.asyncio
async def test_sweep_flags_cron_like_low_engagement_visitor(
    test_db, test_site_id, monkeypatch
):
    from apps.api.models.visitor import IdentifiedVisitor

    await _seed_visitor(
        test_db,
        test_site_id,
        "cadence_bot_probe",
        days=12,
        event_types_per_day=["pageview"],
    )
    test_db.add(
        IdentifiedVisitor(
            site_id=test_site_id,
            visitor_id="cadence_bot_probe",
            email="crawler@example.com",
            resolution_provider="rb2b",
        )
    )
    await test_db.commit()

    counters = await _run_sweep(test_db, monkeypatch)

    assert counters["flagged"] >= 1
    assert await _visitor_flag(test_db, test_site_id, "cadence_bot_probe") is True

    result = await test_db.execute(
        select(IdentifiedVisitor.is_bot_suspect).where(
            IdentifiedVisitor.site_id == test_site_id,
            IdentifiedVisitor.visitor_id == "cadence_bot_probe",
        )
    )
    assert result.scalar_one() is True


@pytest.mark.asyncio
async def test_sweep_does_not_flag_organic_visitor(test_db, test_site_id, monkeypatch):
    await _seed_visitor(
        test_db,
        test_site_id,
        "cadence_human_probe",
        days=12,
        event_types_per_day=["pageview", "scroll", "click"],
        jitter_seconds=9000,
    )

    await _run_sweep(test_db, monkeypatch)

    assert await _visitor_flag(test_db, test_site_id, "cadence_human_probe") is False


@pytest.mark.asyncio
async def test_sweep_respects_lookback_cap(test_db, test_site_id, monkeypatch):
    """Events older than the lookback window are invisible to the sweep."""
    from apps.api.config import settings

    monkeypatch.setattr(settings, "cadence_bot_flag_lookback_days", 7, raising=False)

    # Bot-shaped history, but entirely OUTSIDE the 7-day window.
    await _seed_visitor(
        test_db,
        test_site_id,
        "cadence_stale_probe",
        days=12,
        event_types_per_day=["pageview"],
        day_offset=60,
    )

    await _run_sweep(test_db, monkeypatch)

    assert await _visitor_flag(test_db, test_site_id, "cadence_stale_probe") is False
