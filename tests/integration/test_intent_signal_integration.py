"""Handoff Detection H3 — Docker-gated live-DB integration (AC-H3-1 Hybrid gate).

DOCKER-GATED KNOWN-GAP (contract Test Gate, gap-resolution D): requires a real
Postgres with the H1 ``agent_fetch_events`` table (no new migration this phase).
NOT run in the sandbox that built H3 (Docker daemon unresponsive — same precedent
as H1/H2). Written + collect-clean so it runs the moment a real DB is available.

Close commands (record only — see
process/features/evallayer/backlog/handoff-program-docker-verification-gaps_NOTE_23-07-26.md):

    docker compose -f infra/docker-compose.yml up -d postgres redis
    .venv/bin/python -m pytest tests/integration -k intent_signal -m integration -q
"""

from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.integration


async def test_sweep_alerts_on_real_commercial_fetch(test_db, monkeypatch):
    """Real on-demand fetches of a commercial page → an intent alert is sent.

    Proves the live round-trip: real ``agent_fetch_events`` rows + a real
    ``Site`` → ``run_intent_signal_sweep`` counts them and dispatches the SITE-level
    alert via the (mocked) EmailSender. No person/company claim is made.
    """
    from apps.api.models.agent_fetch_event import AgentFetchEvent
    from apps.api.models.site import Site
    from apps.api.models.user import User
    from apps.api.services import hot_alert
    from apps.api.services.agent_intent_signals import run_intent_signal_sweep

    sent: list[dict] = []

    class _FakeSender:
        async def send(self, **kwargs):
            sent.append(kwargs)

    monkeypatch.setattr(hot_alert, "EmailSender", _FakeSender)

    import uuid as _uuid

    user = User(email="owner-int@example.com")
    test_db.add(user)
    await test_db.commit()

    site = Site(
        site_id="site-h3-int",
        user_id=user.id,
        name="Acme",
        hot_alert_enabled=True,
    )
    test_db.add(site)

    now = datetime.now(timezone.utc)
    for _ in range(4):
        test_db.add(
            AgentFetchEvent(
                site_id="site-h3-int",
                vendor="openai",
                raw_ua_token="gptbot",
                tier="on-demand",
                page_path="/pricing",
                created_at=now - timedelta(hours=1),
            )
        )
    await test_db.commit()

    counters = await run_intent_signal_sweep(test_db)
    assert counters["alerted"] >= 1
    assert len(sent) >= 1

    body = sent[0]["body_html"]
    # SITE-level only — never the owner's email or a person identifier.
    assert "owner-int@example.com" not in body
    assert "Acme" in body


async def test_sweep_ignores_non_commercial_pages(test_db, monkeypatch):
    """Fetches of a non-commercial page never trigger an intent alert."""
    from apps.api.models.agent_fetch_event import AgentFetchEvent
    from apps.api.models.site import Site
    from apps.api.models.user import User
    from apps.api.services import hot_alert
    from apps.api.services.agent_intent_signals import run_intent_signal_sweep

    sent: list[dict] = []

    class _FakeSender:
        async def send(self, **kwargs):
            sent.append(kwargs)

    monkeypatch.setattr(hot_alert, "EmailSender", _FakeSender)

    user = User(email="owner-int2@example.com")
    test_db.add(user)
    await test_db.commit()
    test_db.add(
        Site(
            site_id="site-h3-int2",
            user_id=user.id,
            name="Beta",
            hot_alert_enabled=True,
        )
    )
    now = datetime.now(timezone.utc)
    test_db.add(
        AgentFetchEvent(
            site_id="site-h3-int2",
            vendor="openai",
            raw_ua_token="gptbot",
            tier="on-demand",
            page_path="/blog/post",
            created_at=now - timedelta(hours=1),
        )
    )
    await test_db.commit()

    counters = await run_intent_signal_sweep(test_db)
    assert counters["alerted"] == 0
    assert sent == []
