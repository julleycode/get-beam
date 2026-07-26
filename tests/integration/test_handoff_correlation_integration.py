"""Handoff Detection H2 — Docker-gated live-DB integration (AC-H2-1 Hybrid gate).

DOCKER-GATED KNOWN-GAP (contract Test Gate, gap-resolution D): requires a real
Postgres with the ``agent_handoff_links`` migration applied. NOT run in the
sandbox that built H2 (Docker daemon unresponsive — same precedent as H1). Written
+ collect-clean so it runs the moment a real DB is available.

Close commands (record only — see
process/features/evallayer/backlog/handoff-program-docker-verification-gaps_NOTE_23-07-26.md):

    cd apps/api && ../../.venv/bin/python -m alembic upgrade head
    cd apps/api && ../../.venv/bin/python -m alembic downgrade -1
    cd apps/api && ../../.venv/bin/python -m alembic upgrade head
    .venv/bin/python -m pytest tests/integration/test_handoff_correlation_integration.py -m integration -q
"""

from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.integration


async def test_sweep_links_real_fetch_to_real_click(test_db):
    """A real on-demand fetch + a real same-page AI-referral pageview → a link."""
    from apps.api.models.agent_fetch_event import AgentFetchEvent
    from apps.api.models.agent_handoff_link import AgentHandoffLink
    from apps.api.models.event import Event
    from apps.api.services.agent_handoff_correlation import (
        run_handoff_correlation_sweep,
    )
    from sqlalchemy import select

    now = datetime.now(timezone.utc)
    fetch = AgentFetchEvent(
        site_id="site-int",
        vendor="openai",
        raw_ua_token="gptbot",
        tier="on-demand",
        page_path="/pricing",
    )
    test_db.add(fetch)
    await test_db.commit()

    test_db.add(
        Event(
            site_id="site-int",
            visitor_id="vid-int",
            event_type="pageview",
            page_path="/pricing",
            referrer="https://chatgpt.com/",
            # Event.created_at is a naive column (models/event.py DateTime without
            # tz), matching how prod stores events. Strip tz so asyncpg accepts it.
            created_at=(now + timedelta(seconds=120)).replace(tzinfo=None),
        )
    )
    await test_db.commit()

    counters = await run_handoff_correlation_sweep(test_db)
    assert counters["linked"] == 1

    links = (await test_db.execute(select(AgentHandoffLink))).scalars().all()
    assert len(links) == 1
    assert links[0].visitor_id == "vid-int"
    assert links[0].confidence == "high"


async def test_sweep_is_idempotent_unique_constraint(test_db):
    """Re-running the sweep never double-links the same fetch event."""
    from apps.api.models.agent_fetch_event import AgentFetchEvent
    from apps.api.models.agent_handoff_link import AgentHandoffLink
    from apps.api.models.event import Event
    from apps.api.services.agent_handoff_correlation import (
        run_handoff_correlation_sweep,
    )
    from sqlalchemy import func, select

    now = datetime.now(timezone.utc)
    fetch = AgentFetchEvent(
        site_id="site-int2",
        vendor="openai",
        raw_ua_token="gptbot",
        tier="on-demand",
        page_path="/x",
    )
    test_db.add(fetch)
    await test_db.commit()
    test_db.add(
        Event(
            site_id="site-int2",
            visitor_id="vid-int2",
            event_type="pageview",
            page_path="/x",
            referrer="https://chatgpt.com/",
            # Naive Event.created_at (see prod column type) — strip tz for asyncpg.
            created_at=(now + timedelta(seconds=60)).replace(tzinfo=None),
        )
    )
    await test_db.commit()

    await run_handoff_correlation_sweep(test_db)
    # Second run: the fetch is already linked (NOT EXISTS filter excludes it).
    await run_handoff_correlation_sweep(test_db)

    count = (
        await test_db.execute(select(func.count()).select_from(AgentHandoffLink))
    ).scalar()
    assert count == 1
