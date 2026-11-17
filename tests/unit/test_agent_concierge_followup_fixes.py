"""PR #92 follow-up review fixes for the WS3 agent concierge (unit lane).

One test cluster per fix: _safe_id, idempotency key + release, owner-email
escaping/defang/label, mock short-circuit, notified bool, per-IP cap, overflow
notice, truncate_ip, dashboard visit recording on every tool path.
"""

import math
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks

import apps.api.main  # noqa: F401 — registers every ORM model
from apps.api.config import settings
from tests.unit._agent_concierge_fakes import FakeRedis, make_lead, mock_db

pytestmark = pytest.mark.unit

GOOD = {"use_case": "a", "company_size": "b", "evaluating_against": "c"}


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr("apps.api.services.redis_client.get_redis", lambda: fake)
    return fake


# ── _safe_id ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        (math.nan, None),
        (math.inf, None),
        (-math.inf, None),
        (True, None),
        (False, None),
        (7, 7),
        (1.5, 1.5),
        ("abc", "abc"),
        ("x" * 129, None),
        ({"a": 1}, None),
    ],
)
def test_safe_id(raw, expected):
    from apps.api.routers.agent_mcp import _safe_id

    assert _safe_id(raw) == expected


# ── truncate_ip ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "ip,expected",
    [
        ("203.0.113.77", "203.0.113.0"),
        (" 10.1.2.3 ", "10.1.2.0"),
        ("2001:db8:abcd:1234::1", "2001:db8:abcd::"),
        ("not-an-ip", None),
        ("", None),
        (None, None),
    ],
)
def test_truncate_ip(ip, expected):
    from apps.api.services.agent_gateway import truncate_ip

    assert truncate_ip(ip) == expected


# ── idempotency ───────────────────────────────────────────────────────


def test_idempotency_key_includes_caller():
    from apps.api.services.agent_gateway import _conversion_idempotency_key as k

    assert k("s", "request_quote", GOOD, "1.1.1.1") == k("s", "request_quote", GOOD, "1.1.1.1")
    assert k("s", "request_quote", GOOD, "1.1.1.1") != k("s", "request_quote", GOOD, "2.2.2.2")


async def test_same_params_different_callers_make_two_leads(monkeypatch):
    from apps.api.services import agent_gateway

    monkeypatch.setattr(settings, "agent_concierge_conversion_idempotency_ttl_seconds", 90)
    db = mock_db()
    site = SimpleNamespace(site_id="s1")
    _, id1 = await agent_gateway.handle_conversion_tool(
        db, site, SimpleNamespace(), "request_quote", dict(GOOD), "1.1.1.1"
    )
    _, id2 = await agent_gateway.handle_conversion_tool(
        db, site, SimpleNamespace(), "request_quote", dict(GOOD), "2.2.2.2"
    )
    assert id1 and id2
    assert db.add.call_count == 2


async def test_idempotency_key_released_when_write_fails(monkeypatch, fake_redis):
    from apps.api.services import agent_gateway

    monkeypatch.setattr(settings, "agent_concierge_conversion_idempotency_ttl_seconds", 90)
    db = mock_db()
    db.commit = AsyncMock(side_effect=RuntimeError("db down"))
    site = SimpleNamespace(site_id="s1")
    with pytest.raises(RuntimeError):
        await agent_gateway.handle_conversion_tool(
            db, site, SimpleNamespace(), "request_quote", dict(GOOD), "1.1.1.1"
        )
    assert not any(k.startswith("agent_conv_idem:") for k in fake_redis.store)

    # The retry is a real new lead, not swallowed as a duplicate.
    db.commit = AsyncMock()
    _, lead_id = await agent_gateway.handle_conversion_tool(
        db, site, SimpleNamespace(), "request_quote", dict(GOOD), "1.1.1.1"
    )
    assert lead_id is not None


# ── per-IP daily cap ──────────────────────────────────────────────────


async def test_per_ip_cap_trips_before_site_cap(monkeypatch):
    from apps.api.routers.agent_mcp import _conversion_daily_cap_reached

    monkeypatch.setattr(settings, "agent_concierge_conversion_daily_cap", 20)
    monkeypatch.setattr(settings, "agent_concierge_conversion_per_ip_daily_cap", 3)
    for _ in range(3):
        assert await _conversion_daily_cap_reached("s1", "1.1.1.1") is False
    assert await _conversion_daily_cap_reached("s1", "1.1.1.1") is True
    # Another caller still has budget on the same site.
    assert await _conversion_daily_cap_reached("s1", "2.2.2.2") is False


def test_conversion_cap_defaults():
    from apps.api.config import Settings

    assert Settings.model_fields["agent_concierge_conversion_daily_cap"].default == 20
    assert Settings.model_fields["agent_concierge_conversion_per_ip_daily_cap"].default == 3
    assert Settings.model_fields["agent_concierge_notify_individual_per_day"].default == 3


# ── owner email ───────────────────────────────────────────────────────


def test_defang_and_render_untrusted():
    from apps.api.services.agent_lead_notify import defang, render_untrusted

    assert defang("see https://evil.tld/x") == "see hxxps[://]evil.tld/x"
    assert defang("go www.evil.tld") == "go www[.]evil.tld"
    out = render_untrusted('<a href="https://evil.tld">click</a>')
    assert "<a" not in out and "https://" not in out
    assert "&lt;a" in out and "hxxps[://]" in out
    assert render_untrusted(None) == "&mdash;"


async def _capture_send(monkeypatch):
    from apps.api.services.email_sender import EmailSender

    sent: list = []

    async def _send(self, **kwargs):
        sent.append(kwargs)
        return {"id": "x"}

    monkeypatch.setattr(EmailSender, "send", _send)
    return sent


async def test_email_escapes_and_labels_agent_fields(monkeypatch):
    from apps.api.services.agent_lead_notify import notify_owner_of_lead

    monkeypatch.setattr(settings, "mock_external_apis", False)
    sent = await _capture_send(monkeypatch)
    lead = make_lead(1, use_case="<script>x</script> visit https://evil.tld")
    ok = await notify_owner_of_lead(mock_db(), SimpleNamespace(site_id="s1", user_id="u"), lead)
    assert ok is True
    body = sent[0]["body_html"]
    assert "<script>" not in body and "https://evil.tld" not in body
    assert "&lt;script&gt;" in body and "hxxps[://]evil.tld" in body
    assert "Unverified agent-supplied input" in body


async def test_mock_mode_sends_nothing_and_returns_false(monkeypatch):
    from apps.api.services.agent_lead_notify import notify_owner_of_lead

    monkeypatch.setattr(settings, "mock_external_apis", True)
    sent = await _capture_send(monkeypatch)
    ok = await notify_owner_of_lead(mock_db(), SimpleNamespace(site_id="s1", user_id="u"), make_lead())
    assert ok is False and sent == []


async def test_no_owner_returns_false(monkeypatch):
    from apps.api.services.agent_lead_notify import notify_owner_of_lead

    monkeypatch.setattr(settings, "mock_external_apis", False)
    sent = await _capture_send(monkeypatch)
    db = mock_db()
    db.execute.return_value.first.return_value = None
    ok = await notify_owner_of_lead(db, SimpleNamespace(site_id="s1", user_id="u"), make_lead())
    assert ok is False and sent == []


async def test_overflow_notice_then_silence(monkeypatch):
    from apps.api.services.agent_lead_notify import notify_owner_of_lead

    monkeypatch.setattr(settings, "mock_external_apis", False)
    monkeypatch.setattr(settings, "agent_concierge_notify_individual_per_day", 3)
    sent = await _capture_send(monkeypatch)
    site = SimpleNamespace(site_id="s-overflow", user_id="u")
    results = [
        await notify_owner_of_lead(mock_db(), site, make_lead(i)) for i in range(1, 7)
    ]
    assert results == [True, True, True, True, False, False]
    assert len(sent) == 4
    assert all("New request_quote lead" in s["subject"] for s in sent[:3])
    assert sent[3]["subject"] == "More AI agent concierge leads today"


async def test_background_task_leaves_notified_false_when_not_sent(monkeypatch):
    from apps.api.services import agent_gateway
    from tests.unit._agent_concierge_fakes import FakeSession

    monkeypatch.setattr(settings, "mock_external_apis", True)
    lead = make_lead(9)
    sess = FakeSession(lead, SimpleNamespace(site_id="site-1", user_id="u"))
    monkeypatch.setattr("apps.api.models.database.async_session", lambda: sess)
    await agent_gateway.process_new_lead(lead.id, None)
    assert lead.notified is False


async def test_background_task_swallows_errors(monkeypatch):
    from apps.api.services import agent_gateway

    def _boom():
        raise RuntimeError("db gone")

    monkeypatch.setattr("apps.api.models.database.async_session", _boom)
    await agent_gateway.process_new_lead(make_lead().id, "1.1.1.1")  # no raise


# ── dispatch: visits on every path, background task scheduling ────────


class _Req:
    client = SimpleNamespace(host="203.0.113.9")
    headers: dict = {}


@pytest.fixture
def order(monkeypatch):
    from apps.api.routers import agent_mcp

    seen: list = []

    async def _visit(db, request, site_id, surface):
        seen.append(("visit", surface))

    async def _record(*a, **k):
        seen.append(("record",))

    monkeypatch.setattr(agent_mcp, "record_gateway_visit", _visit)
    monkeypatch.setattr(agent_mcp, "_record_tool_call", _record)
    return seen


def _tool(seen):
    def _t(site, profile, params=None):
        seen.append(("tool",))
        return {"ok": True}

    return _t


async def test_visit_on_ungated_read(monkeypatch, order):
    from apps.api.routers import agent_mcp
    from apps.api.services import agent_gateway

    monkeypatch.setattr(settings, "agent_concierge_qualification_enabled", False)
    monkeypatch.setitem(agent_gateway.MCP_TOOLS, "get_offers", _tool(order))
    await agent_mcp._dispatch_tool(
        mock_db(), _Req(), BackgroundTasks(), SimpleNamespace(site_id="s"),
        SimpleNamespace(), 1, "get_offers", {},
    )
    assert [o[0] for o in order] == ["tool", "visit", "record"]


async def test_visit_on_gated_read_and_needs_more_info(monkeypatch, order):
    from apps.api.routers import agent_mcp
    from apps.api.services import agent_gateway

    monkeypatch.setattr(settings, "agent_concierge_qualification_enabled", True)
    monkeypatch.setitem(agent_gateway.MCP_TOOLS, "get_pricing", _tool(order))
    site = SimpleNamespace(site_id="s")
    await agent_mcp._dispatch_tool(
        mock_db(), _Req(), BackgroundTasks(), site, SimpleNamespace(), 1, "get_pricing", GOOD
    )
    assert [o[0] for o in order] == ["tool", "visit", "record"]
    order.clear()
    await agent_mcp._dispatch_tool(
        mock_db(), _Req(), BackgroundTasks(), site, SimpleNamespace(), 1, "get_pricing", {}
    )
    assert [o[0] for o in order] == ["visit", "record"]


async def test_conversion_schedules_background_and_records_visit(monkeypatch, order):
    from apps.api.routers import agent_mcp

    monkeypatch.setattr(settings, "agent_concierge_conversion_enabled", True)
    monkeypatch.setattr(settings, "agent_concierge_conversion_daily_cap", 0)

    async def _handle(db, site, profile, tool_name, params, ip):
        order.append(("handle",))
        return {"lead_created": True}, "lead-123"

    monkeypatch.setattr(agent_mcp, "handle_conversion_tool", _handle)
    monkeypatch.setattr(agent_mcp, "_conversion_rate_limited", lambda s: False)
    bg = BackgroundTasks()
    resp = await agent_mcp._dispatch_tool(
        mock_db(), _Req(), bg, SimpleNamespace(site_id="s"), SimpleNamespace(),
        1, "request_quote", GOOD,
    )
    assert resp.status_code == 200
    assert [o[0] for o in order] == ["handle", "visit", "record"]
    assert len(bg.tasks) == 1
    assert bg.tasks[0].func is agent_mcp.process_new_lead
    assert bg.tasks[0].args == ("lead-123", "203.0.113.9")


async def test_duplicate_conversion_schedules_nothing(monkeypatch, order):
    from apps.api.routers import agent_mcp

    monkeypatch.setattr(settings, "agent_concierge_conversion_enabled", True)
    monkeypatch.setattr(settings, "agent_concierge_conversion_daily_cap", 0)

    async def _handle(*a):
        return {"lead_created": True}, None

    monkeypatch.setattr(agent_mcp, "handle_conversion_tool", _handle)
    monkeypatch.setattr(agent_mcp, "_conversion_rate_limited", lambda s: False)
    bg = BackgroundTasks()
    await agent_mcp._dispatch_tool(
        mock_db(), _Req(), bg, SimpleNamespace(site_id="s"), SimpleNamespace(),
        1, "request_quote", GOOD,
    )
    assert bg.tasks == []


async def test_tool_call_row_cap(monkeypatch):
    from apps.api.routers.agent_mcp import _tool_call_row_cap_reached

    monkeypatch.setattr(settings, "agent_tool_calls_daily_row_cap", 2)
    assert await _tool_call_row_cap_reached("s") is False
    assert await _tool_call_row_cap_reached("s") is False
    assert await _tool_call_row_cap_reached("s") is True


def test_hash_ip_never_returns_raw_ip():
    from apps.api.routers.agent_mcp import _hash_ip

    h = _hash_ip("203.0.113.9")
    assert h is None or ("203.0.113.9" not in h and len(h) == 32)
    assert _hash_ip(None) is None
