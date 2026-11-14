"""Unit tests: GDPR erasure-gap closures (no DB).

- EmailSender mock-mode short-circuit (never reaches SendGrid).
- KG-8 cumulative daily cap decision.
- retention purge predicates + scheduler wiring.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.config import settings
from apps.api.services import graph_erasure as ge
from apps.api.services import retention
from apps.api.services.email_sender import EmailSender


# ─────────────────────────── email mock mode ───────────────────────────


@pytest.mark.asyncio
async def test_mock_mode_never_calls_sendgrid(monkeypatch):
    monkeypatch.setattr(settings, "mock_external_apis", True)
    with patch("apps.api.services.email_sender.httpx.AsyncClient") as client_cls:
        a = await EmailSender().send("p@example.com", "hi", "<p>x</p>")
        b = await EmailSender().send("p@example.com", "hi", "<p>x</p>")
    client_cls.assert_not_called()
    assert a["status"] == 202 and a["id"].startswith("mock-")
    assert a == b, "mock id must be deterministic"
    assert "p@example.com" not in a["id"]


@pytest.mark.asyncio
async def test_mock_mode_still_honours_suppression(monkeypatch):
    monkeypatch.setattr(settings, "mock_external_apis", True)
    sender = EmailSender()
    monkeypatch.setattr(sender, "_is_suppressed", AsyncMock(return_value=True))
    assert await sender.send("p@example.com", "hi", "<p>x</p>", db=MagicMock()) is None


@pytest.mark.asyncio
async def test_real_path_unchanged_when_mock_off(monkeypatch):
    monkeypatch.setattr(settings, "mock_external_apis", False)
    resp = MagicMock(status_code=202, headers={"X-Message-Id": "real-1"}, text="")
    client = AsyncMock()
    client.post.return_value = resp
    with patch("apps.api.services.email_sender.httpx.AsyncClient") as client_cls:
        client_cls.return_value.__aenter__.return_value = client
        out = await EmailSender().send("p@example.com", "hi", "<p>x</p>")
    assert out == {"id": "real-1", "status": 202}
    client.post.assert_awaited_once()


# ─────────────────────────── KG-8 daily cap ───────────────────────────


def _db_returning(count: int) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar.return_value = count
    db.execute.return_value = result
    return db


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cap,count,expected",
    [(10, 9, False), (10, 10, True), (10, 11, True), (0, 10**6, False)],
)
async def test_daily_cap(monkeypatch, cap, count, expected):
    monkeypatch.setattr(settings, "graph_erasure_max_per_day", cap)
    db = _db_returning(count)
    assert await ge.daily_cap_exceeded(db, "site") is expected
    if cap <= 0:
        db.execute.assert_not_called()


def test_daily_cap_default_is_enforcing():
    assert settings.graph_erasure_max_per_day > settings.graph_erasure_max_per_minute


# ─────────────────────────── retention ───────────────────────────


def test_retention_defaults():
    assert settings.identity_feedback_retention_days == 90
    assert settings.social_context_retention_days == 180


def test_social_context_predicate_only_touches_nonnull_blobs():
    assert "social_context IS NOT NULL" in retention._SOCIAL_CONTEXT_WHERE
    assert "COALESCE(social_context_updated_at, updated_at)" in retention._SOCIAL_CONTEXT_WHERE


@pytest.mark.asyncio
async def test_scheduler_runs_new_purges_even_if_earlier_ones_crash(monkeypatch):
    from apps.api.jobs import scheduler

    boom = AsyncMock(side_effect=RuntimeError("x"))
    fb = AsyncMock(return_value={"status": "ok", "deleted": 0})
    sc = AsyncMock(return_value={"status": "ok", "deleted": 0})
    monkeypatch.setattr(scheduler, "purge_events_older_than", boom)
    monkeypatch.setattr(scheduler, "purge_agent_fetch_events_older_than", boom)
    monkeypatch.setattr(scheduler, "purge_request_logs_older_than", boom)
    monkeypatch.setattr(scheduler, "purge_identity_feedback_older_than", fb)
    monkeypatch.setattr(scheduler, "purge_social_context_older_than", sc)

    await scheduler._retention_purge_job()

    fb.assert_awaited_once()
    sc.assert_awaited_once()
