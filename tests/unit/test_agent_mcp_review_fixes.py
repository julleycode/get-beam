"""WS3 security-review fixes — H1 / M1 / M2 / M3 / M4 (unit lane).

One focused test (or small cluster) per review finding. No live DB / Redis: the
Redis-backed guards are exercised with an in-memory fake, and the fail-open paths
are exercised by simply having no Redis (get_redis raises → guard returns False).
"""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import apps.api.main  # noqa: F401 — registers every ORM model
from apps.api.config import settings

pytestmark = pytest.mark.unit


# ── shared fakes ──────────────────────────────────────────────────────


class FakeRedis:
    """Minimal async Redis supporting SET NX EX + INCR/EXPIRE semantics."""

    def __init__(self):
        self.store: dict = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None  # NX failed → duplicate
        self.store[key] = value
        return True

    async def incr(self, key):
        self.store[key] = int(self.store.get(key, 0)) + 1
        return self.store[key]

    async def expire(self, key, seconds):
        return True


@pytest.fixture(autouse=True)
def _hermetic_redis(monkeypatch):
    """Unit lane assumes NO local Redis, but a stray container on :6379 poisons
    the idempotency/daily-cap keys across runs. Give every test a FRESH in-memory
    fake so the Redis-backed guards are deterministic and never touch a real
    server (documented `fix = mock get_redis` pattern). Tests that need a raising
    get_redis re-patch it themselves (last monkeypatch wins). ONE fake instance
    per test so SET-NX / INCR state is shared within a test but never across."""
    fake = FakeRedis()
    monkeypatch.setattr(
        "apps.api.services.redis_client.get_redis", lambda: fake
    )
    return fake


def _mock_db():
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()
    owner_row = MagicMock()
    owner_row.first.return_value = ("owner@example.com",)
    db.execute = AsyncMock(return_value=owner_row)
    return db


class _FakeRequest:
    client = SimpleNamespace(host="203.0.113.9")
    headers: dict = {}


def _body(resp):
    return json.loads(resp.body)


# ══════════════════════════════════════════════════════════════════════
# H1 — body-size guard now covers the dynamic /mcp path
# ══════════════════════════════════════════════════════════════════════


def test_cap_for_path_guards_mcp_and_ingest():
    from apps.api.main import IngestBodySizeLimitMiddleware
    from apps.api.routers.agent_mcp import MAX_MCP_BODY_BYTES

    cls = IngestBodySizeLimitMiddleware
    assert cls._cap_for_path("/api/v1/events/ingest") == settings.ingest_body_max_bytes
    # Dynamic site_id segment must be matched (prefix+suffix), with the MCP cap.
    assert cls._cap_for_path("/api/v1/agent/site_abc/mcp") == MAX_MCP_BODY_BYTES
    assert cls._cap_for_path("/api/v1/agent/anything-here/mcp") == MAX_MCP_BODY_BYTES
    # Unrelated paths are unguarded.
    assert cls._cap_for_path("/api/v1/agent/site_abc/manifest.json") is None
    assert cls._cap_for_path("/api/v1/campaigns") is None


async def test_chunked_oversized_mcp_body_rejected_before_full_buffer():
    """A chunked / no-Content-Length oversized body to /mcp is rejected 413 by the
    ASGI middleware, and the downstream app never sees the full oversized body —
    the running byte-counter aborts receive() before Starlette buffers it all (H1).

    Driven directly against the middleware with a dummy downstream app so no DB is
    needed (the real /mcp endpoint queries the tenant before reading the body)."""
    from apps.api.main import IngestBodySizeLimitMiddleware
    from apps.api.routers.agent_mcp import MAX_MCP_BODY_BYTES

    seen = {"body_len": 0, "called": False}

    async def dummy_app(scope, receive, send):
        seen["called"] = True
        body = b""
        while True:
            msg = await receive()
            body += msg.get("body", b"")
            if not msg.get("more_body"):
                break
        seen["body_len"] = len(body)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    mw = IngestBodySizeLimitMiddleware(dummy_app)

    total = MAX_MCP_BODY_BYTES + 8192
    chunk = 4096
    n_chunks = total // chunk
    messages = [
        {"type": "http.request", "body": b"A" * chunk, "more_body": i < n_chunks - 1}
        for i in range(n_chunks)
    ]
    it = iter(messages)

    async def receive():
        try:
            return next(it)
        except StopIteration:
            return {"type": "http.request", "body": b"", "more_body": False}

    sent: list = []

    async def send(message):
        sent.append(message)

    # No content-length header → only the running counter can guard this.
    scope = {"type": "http", "path": "/api/v1/agent/site_abc/mcp", "headers": []}
    await mw(scope, receive, send)

    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 413
    # The downstream app never received the full oversized body.
    assert seen["body_len"] <= MAX_MCP_BODY_BYTES
    assert seen["body_len"] < total


# ══════════════════════════════════════════════════════════════════════
# M1 — read-tool result computed BEFORE the fail-open metric write
# ══════════════════════════════════════════════════════════════════════


async def test_gated_read_tool_computes_result_before_metric(monkeypatch):
    from apps.api.routers import agent_mcp
    from apps.api.services import agent_gateway

    monkeypatch.setattr(settings, "agent_concierge_qualification_enabled", True)
    monkeypatch.setattr(settings, "agent_concierge_conversion_enabled", False)

    order: list[str] = []

    def _fake_tool(site, profile, params=None):
        order.append("tool")
        return {"ok": True}

    async def _fake_record(*a, **k):
        order.append("record")

    monkeypatch.setitem(agent_gateway.MCP_TOOLS, "get_pricing", _fake_tool)
    monkeypatch.setattr(agent_mcp, "_record_tool_call", _fake_record)

    db = _mock_db()
    site = SimpleNamespace(site_id="s1")
    profile = SimpleNamespace()
    resp = await agent_mcp._dispatch_tool(
        db,
        _FakeRequest(),
        site,
        profile,
        1,
        "get_pricing",
        {"use_case": "a", "company_size": "b", "evaluating_against": "c"},
    )
    # The tool ran STRICTLY before the metric write (so a metric rollback that
    # expires ORM attrs can never break a tool call → no MissingGreenlet 500).
    assert order == ["tool", "record"]
    assert _body(resp)["result"] == {"ok": True}


async def test_ungated_read_tool_computes_result_before_metric(monkeypatch):
    from apps.api.routers import agent_mcp
    from apps.api.services import agent_gateway

    monkeypatch.setattr(settings, "agent_concierge_qualification_enabled", False)
    monkeypatch.setattr(settings, "agent_concierge_conversion_enabled", True)  # any-flag-on → records

    order: list[str] = []

    def _fake_tool(site, profile, params=None):
        order.append("tool")
        return {"ok": True}

    async def _fake_record(*a, **k):
        order.append("record")

    monkeypatch.setitem(agent_gateway.MCP_TOOLS, "get_offers", _fake_tool)
    monkeypatch.setattr(agent_mcp, "_record_tool_call", _fake_record)

    resp = await agent_mcp._dispatch_tool(
        _mock_db(), _FakeRequest(), SimpleNamespace(site_id="s1"), SimpleNamespace(),
        1, "get_offers", {},
    )
    assert order == ["tool", "record"]
    assert _body(resp)["result"] == {"ok": True}


# ══════════════════════════════════════════════════════════════════════
# M2 — attacker-controllable rDNS PTR domain sanitized before store + email
# ══════════════════════════════════════════════════════════════════════


def test_sanitize_resolved_domain_grammar():
    from apps.api.services.agent_gateway import sanitize_resolved_domain

    assert sanitize_resolved_domain("acme.example") == "acme.example"
    assert sanitize_resolved_domain("Sub.Acme.CO.UK") == "sub.acme.co.uk"
    # Hostile / malformed → dropped to None (never stored, never interpolated).
    assert sanitize_resolved_domain("<script>evil.example") is None
    assert sanitize_resolved_domain("no-dot") is None
    assert sanitize_resolved_domain("a b.com") is None
    assert sanitize_resolved_domain("evil<img>.com") is None
    assert sanitize_resolved_domain("") is None
    assert sanitize_resolved_domain(None) is None
    assert sanitize_resolved_domain("x" * 300 + ".com") is None


async def test_hostile_ptr_domain_not_stored_or_emailed(monkeypatch):
    from apps.api.services import agent_gateway, company_resolver
    from apps.api.services.email_sender import EmailSender

    # No idempotency interference: no Redis → _conversion_is_duplicate fail-open False.
    async def _free(ip, db=None):
        return "<script>evil.example"  # hostile PTR

    monkeypatch.setattr(company_resolver, "resolve_company_cached", _free)

    captured: dict = {}

    async def _send(self, **kwargs):
        captured.update(kwargs)
        return {"id": "x"}

    monkeypatch.setattr(EmailSender, "send", _send)

    added: dict = {}
    db = _mock_db()
    db.add = MagicMock(side_effect=lambda obj: added.__setitem__("lead", obj))

    site = SimpleNamespace(site_id="s1", user_id="u1")
    profile = SimpleNamespace(qualified_content={})
    result = await agent_gateway.handle_conversion_tool(
        db, site, profile, "request_quote",
        {"use_case": "a", "company_size": "b", "evaluating_against": "c"},
        ip_address="203.0.113.5",
    )
    assert result["lead_created"] is True
    # Hostile domain dropped before the row was built …
    assert added["lead"].resolved_company_domain is None
    # … and never reaches the email body (falls back to 'unknown').
    assert "<script>" not in captured.get("body_html", "")
    assert "unknown" in captured.get("body_html", "")


# ══════════════════════════════════════════════════════════════════════
# M3 — daily cap + idempotency
# ══════════════════════════════════════════════════════════════════════


async def test_daily_cap_trips_after_ceiling(monkeypatch):
    from apps.api.routers.agent_mcp import _conversion_daily_cap_reached

    fake = FakeRedis()
    monkeypatch.setattr("apps.api.services.redis_client.get_redis", lambda: fake)
    monkeypatch.setattr(settings, "agent_concierge_conversion_daily_cap", 2)

    assert await _conversion_daily_cap_reached("s1") is False  # 1
    assert await _conversion_daily_cap_reached("s1") is False  # 2
    assert await _conversion_daily_cap_reached("s1") is True   # 3 > 2


async def test_daily_cap_disabled_when_zero(monkeypatch):
    from apps.api.routers.agent_mcp import _conversion_daily_cap_reached

    monkeypatch.setattr(settings, "agent_concierge_conversion_daily_cap", 0)
    # Even without touching Redis, a 0 cap is an explicit opt-out → never trips.
    assert await _conversion_daily_cap_reached("s1") is False


async def test_daily_cap_fail_open_without_redis(monkeypatch):
    from apps.api.routers.agent_mcp import _conversion_daily_cap_reached

    monkeypatch.setattr(settings, "agent_concierge_conversion_daily_cap", 1)

    def _boom():
        raise RuntimeError("no redis")

    monkeypatch.setattr("apps.api.services.redis_client.get_redis", _boom)
    assert await _conversion_daily_cap_reached("s1") is False  # fail-open


async def test_idempotency_collapses_duplicate_conversions(monkeypatch):
    from apps.api.services import agent_gateway, company_resolver
    from apps.api.services.email_sender import EmailSender

    fake = FakeRedis()
    monkeypatch.setattr("apps.api.services.redis_client.get_redis", lambda: fake)
    monkeypatch.setattr(settings, "agent_concierge_conversion_idempotency_ttl_seconds", 90)

    async def _free(ip, db=None):
        return None

    monkeypatch.setattr(company_resolver, "resolve_company_cached", _free)

    send_count = {"n": 0}

    async def _send(self, **kwargs):
        send_count["n"] += 1
        return {"id": "x"}

    monkeypatch.setattr(EmailSender, "send", _send)

    db = _mock_db()
    site = SimpleNamespace(site_id="s1", user_id="u1")
    profile = SimpleNamespace(qualified_content={})
    params = {"use_case": "a", "company_size": "b", "evaluating_against": "c"}

    r1 = await agent_gateway.handle_conversion_tool(
        db, site, profile, "request_quote", dict(params), "203.0.113.1"
    )
    r2 = await agent_gateway.handle_conversion_tool(
        db, site, profile, "request_quote", dict(params), "203.0.113.1"
    )
    assert r1["lead_created"] is True and r2["lead_created"] is True
    # The 2nd identical call collapsed: only ONE lead row + ONE email.
    assert db.add.call_count == 1
    assert send_count["n"] == 1


async def test_idempotency_distinct_params_not_collapsed(monkeypatch):
    from apps.api.services import agent_gateway, company_resolver
    from apps.api.services.email_sender import EmailSender

    fake = FakeRedis()
    monkeypatch.setattr("apps.api.services.redis_client.get_redis", lambda: fake)
    monkeypatch.setattr(settings, "agent_concierge_conversion_idempotency_ttl_seconds", 90)

    async def _free(ip, db=None):
        return None

    monkeypatch.setattr(company_resolver, "resolve_company_cached", _free)
    monkeypatch.setattr(EmailSender, "send", AsyncMock(return_value={"id": "x"}))

    db = _mock_db()
    site = SimpleNamespace(site_id="s1", user_id="u1")
    profile = SimpleNamespace(qualified_content={})

    await agent_gateway.handle_conversion_tool(
        db, site, profile, "request_quote",
        {"use_case": "a", "company_size": "b", "evaluating_against": "c"}, "203.0.113.1",
    )
    await agent_gateway.handle_conversion_tool(
        db, site, profile, "request_quote",
        {"use_case": "DIFFERENT", "company_size": "b", "evaluating_against": "c"}, "203.0.113.1",
    )
    # Different params → two distinct leads (idempotency must not over-collapse).
    assert db.add.call_count == 2


# ══════════════════════════════════════════════════════════════════════
# M4 — incomplete (zero-cost) calls do not starve the tight conversion budget
# ══════════════════════════════════════════════════════════════════════


async def test_incomplete_conversion_calls_do_not_starve_complete(monkeypatch):
    from apps.api.routers import agent_mcp

    monkeypatch.setattr(settings, "agent_concierge_conversion_enabled", True)
    # Tight budget of 1/min; disable daily cap + idempotency to isolate the minute
    # bucket behaviour under test.
    monkeypatch.setattr(settings, "agent_concierge_conversion_rate_limit_per_minute", 1)
    monkeypatch.setattr(settings, "agent_concierge_conversion_daily_cap", 0)
    monkeypatch.setattr(settings, "agent_concierge_conversion_idempotency_ttl_seconds", 0)

    async def _fake_handle(db, site, profile, tool_name, params, ip):
        return {"lead_created": True, "tool_name": tool_name}

    async def _fake_record(*a, **k):
        return None

    monkeypatch.setattr(agent_mcp, "handle_conversion_tool", _fake_handle)
    monkeypatch.setattr(agent_mcp, "_record_tool_call", _fake_record)

    # Unique site so the shared in-memory limiter bucket is fresh for this test.
    site = SimpleNamespace(site_id=f"s-{uuid.uuid4().hex}")
    profile = SimpleNamespace()
    db = _mock_db()

    # Fire many INCOMPLETE calls (missing params) — must NOT drain the 1/min bucket.
    for _ in range(10):
        resp = await agent_mcp._dispatch_tool(
            db, _FakeRequest(), site, profile, 1, "request_quote", {}
        )
        assert _body(resp)["result"]["needs_more_info"] is True

    good = {"use_case": "a", "company_size": "b", "evaluating_against": "c"}
    # First COMPLETE call still succeeds (budget was never consumed by the empties).
    ok = await agent_mcp._dispatch_tool(
        db, _FakeRequest(), site, profile, 1, "request_quote", good
    )
    assert _body(ok)["result"]["lead_created"] is True

    # Second COMPLETE call is now rate-limited → proves COMPLETE calls DO consume.
    limited = await agent_mcp._dispatch_tool(
        db, _FakeRequest(), site, profile, 1, "request_quote", good
    )
    assert limited.status_code == 429
    assert _body(limited)["error"]["code"] == -32010
