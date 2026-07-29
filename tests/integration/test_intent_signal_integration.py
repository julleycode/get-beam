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

    # Fresh ids per run. The alert path holds a per-site/page cooldown, so a fixed
    # site_id makes this pass exactly once against a given database and report
    # "alerted: 0" on every run after — a failure that says nothing about the
    # behaviour under test. Every other integration file here randomises for the
    # same reason.
    suffix = _uuid.uuid4().hex[:8]
    site_id = f"site-h3-int-{suffix}"

    user = User(email=f"owner-int-{suffix}@example.com")
    test_db.add(user)
    await test_db.commit()

    # sites.url is NOT NULL — omitting it fails the insert before any intent
    # signal is exercised.
    site = Site(
        site_id=site_id,
        user_id=user.id,
        name="Acme",
        url="https://acme.example.com",
        hot_alert_enabled=True,
    )
    test_db.add(site)

    now = datetime.now(timezone.utc)
    for _ in range(4):
        test_db.add(
            AgentFetchEvent(
                site_id=site_id,
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

    # The sweep covers every site in the database, so pick THIS site's alert
    # rather than whichever happened to be sent first — other rows left by
    # neighbouring tests would otherwise decide what gets asserted here.
    bodies = [k["body_html"] for k in sent if "Acme" in k.get("body_html", "")]
    assert bodies, "no intent alert was sent for this test's site"
    body = bodies[0]
    # SITE-level only — never the owner's email or a person identifier.
    assert f"owner-int-{suffix}@example.com" not in body
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

    import uuid as _uuid

    # Fresh ids per run, as above.
    suffix = _uuid.uuid4().hex[:8]
    site_id = f"site-h3-int2-{suffix}"
    site_name = f"Beta-{suffix}"

    user = User(email=f"owner-int2-{suffix}@example.com")
    test_db.add(user)
    await test_db.commit()
    test_db.add(
        Site(
            site_id=site_id,
            user_id=user.id,
            name=site_name,
            url="https://beta.example.com",
            hot_alert_enabled=True,
        )
    )
    now = datetime.now(timezone.utc)
    test_db.add(
        AgentFetchEvent(
            site_id=site_id,
            vendor="openai",
            raw_ua_token="gptbot",
            tier="on-demand",
            page_path="/blog/post",
            created_at=now - timedelta(hours=1),
        )
    )
    await test_db.commit()

    await run_intent_signal_sweep(test_db)
    # Scoped to THIS site. A global "alerted == 0" would be asserting that no
    # other site in the database has commercial traffic, which is not this test's
    # claim and is false as soon as another test leaves a row behind.
    assert not [k for k in sent if site_name in k.get("body_html", "")]
