"""Agent-gateway Phase 2 — hand-written JSON-RPC MCP server (AC9, AC9b).

Two things under test:

* **AC9 — no drift.** MCP tool output must be derived from the same
  ``AgentProfile`` assembly the REST endpoints use. A separate code path that
  happens to agree today would silently diverge tomorrow, so the tests compare
  MCP output against the REST response rather than against a fixture.
* **AC9b — the four E3 guards.** Method allow-list, body-size cap, malformed
  JSON-RPC error shape, and no echo of raw input into error responses.

In-process ASGI tests with ``get_db`` overridden. Unit lane.
"""

import json
import uuid
from datetime import datetime, timezone

import pytest

import apps.api.main  # noqa: F401 — registers every ORM model
from httpx import ASGITransport, AsyncClient

from apps.api.config import settings
from apps.api.main import app
from apps.api.models.agent_profile import AgentProfile
from apps.api.models.database import get_db
from apps.api.models.site import Site
from apps.api.routers.agent_mcp import MAX_MCP_BODY_BYTES
from apps.api.services.agent_gateway import MCP_TOOLS

pytestmark = pytest.mark.unit

MCP_PATH = "/api/v1/agent/site_abc/mcp"


@pytest.fixture(autouse=True)
def _no_rate_limit():
    """Disable the shared slowapi limiter for the duration of this module.

    The limiter holds in-process state that is shared across every test file in
    the run, so by the time this module executes in the full unit lane the
    ``/mcp`` route's ``60 per 1 minute`` budget can already be exhausted by
    earlier files and requests come back 429 instead of 200. Same pattern as the
    integration ``test_client`` fixture in ``tests/conftest.py``.

    This only changes runtime behaviour inside the test process. The production
    rate limit on the route is untouched — ``test_mcp_route_is_rate_limited``
    still asserts the ``@limiter.limit(...)`` decorator is present in the router
    source.
    """
    from apps.api.services.rate_limiter import limiter

    prev = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = prev


class _Result:
    def __init__(self, value):
        self._value = value

    def first(self):
        return self._value


class FakeSession:
    def __init__(self, row):
        self._row = row

    async def execute(self, _stmt):
        return _Result(self._row)


def _site():
    return Site(
        id=uuid.uuid4(),
        site_id="site_abc",
        user_id=uuid.uuid4(),
        name="Acme",
        url="https://acme.example",
        description="Site-level description",
    )


def _profile(enabled=True):
    now = datetime(2026, 7, 26, tzinfo=timezone.utc)
    return AgentProfile(
        id=uuid.uuid4(),
        site_id="site_abc",
        enabled=enabled,
        tagline="Widgets, fast",
        long_description="We make widgets.",
        offers=[
            {
                "name": "Pro",
                "price": "49",
                "currency": "USD",
                "billing_period": "month",
                "availability": "in_stock",
                "url": "https://acme.example/pro",
            }
        ],
        capabilities=["request_demo"],
        primary_cta="Book a demo",
        privacy_policy_url=None,
        tos_url=None,
        contact_email=None,
        created_at=now,
        updated_at=now,
    )


def _client(row):
    app.dependency_overrides[get_db] = lambda: FakeSession(row)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _reset():
    app.dependency_overrides.clear()


def _rpc(method, params=None, request_id=1):
    body = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


@pytest.fixture
def gateway_on(monkeypatch):
    monkeypatch.setattr(settings, "agent_gateway_enabled", True)


# ── Gating parity with the REST surface (AC6/AC8 for the MCP route) ───


async def test_404_when_global_flag_off(monkeypatch):
    monkeypatch.setattr(settings, "agent_gateway_enabled", False)
    try:
        async with _client((_site(), _profile())) as client:
            resp = await client.post(MCP_PATH, json=_rpc("get_offers"))
        assert resp.status_code == 404
    finally:
        _reset()


async def test_404_when_profile_disabled(gateway_on):
    try:
        async with _client((_site(), _profile(enabled=False))) as client:
            resp = await client.post(MCP_PATH, json=_rpc("get_offers"))
        assert resp.status_code == 404
    finally:
        _reset()


async def test_unknown_site_404_never_403(gateway_on):
    try:
        async with _client(None) as client:
            resp = await client.post(MCP_PATH, json=_rpc("get_offers"))
        assert resp.status_code == 404
        assert resp.status_code != 403
    finally:
        _reset()


# ── AC9: MCP output must not drift from REST output ───────────────────


async def test_get_offers_matches_rest_offers_endpoint(gateway_on):
    try:
        async with _client((_site(), _profile())) as client:
            rest = (await client.get("/api/v1/agent/site_abc/offers.json")).json()
            rpc = (await client.post(MCP_PATH, json=_rpc("get_offers"))).json()
        assert rpc["result"] == rest
    finally:
        _reset()


async def test_pricing_and_availability_derive_from_the_same_offers(gateway_on):
    try:
        async with _client((_site(), _profile())) as client:
            rest = (await client.get("/api/v1/agent/site_abc/offers.json")).json()
            pricing = (await client.post(MCP_PATH, json=_rpc("get_pricing"))).json()
            avail = (
                await client.post(MCP_PATH, json=_rpc("check_availability"))
            ).json()
    finally:
        _reset()

    rest_ids = [o["item_id"] for o in rest["offers"]]
    assert [p["item_id"] for p in pricing["result"]["pricing"]] == rest_ids
    assert [a["item_id"] for a in avail["result"]["availability"]] == rest_ids
    assert pricing["result"]["pricing"][0]["price"] == rest["offers"][0]["price"]
    assert (
        avail["result"]["availability"][0]["availability"]
        == rest["offers"][0]["availability"]
    )


async def test_tools_call_wrapper_matches_bare_method(gateway_on):
    try:
        async with _client((_site(), _profile())) as client:
            bare = (await client.post(MCP_PATH, json=_rpc("get_offers"))).json()
            wrapped = (
                await client.post(
                    MCP_PATH, json=_rpc("tools/call", {"name": "get_offers"})
                )
            ).json()
        assert bare["result"] == wrapped["result"]
    finally:
        _reset()


async def test_tools_list_advertises_exactly_the_allowlisted_tools(gateway_on):
    try:
        async with _client((_site(), _profile())) as client:
            resp = await client.post(MCP_PATH, json=_rpc("tools/list"))
        listed = {t["name"] for t in resp.json()["result"]["tools"]}
        assert listed == set(MCP_TOOLS)
    finally:
        _reset()


async def test_no_write_or_action_tool_is_exposed_in_phase_2():
    """Phase 3 adds the action tools. They must not exist yet."""
    assert set(MCP_TOOLS) == {"get_offers", "get_pricing", "check_availability"}
    for forbidden in ("request_demo", "get_quote", "join_waitlist", "start_checkout"):
        assert forbidden not in MCP_TOOLS


# ── WS3: initialize lifecycle handshake ───────────────────────────────


async def test_initialize_returns_static_handshake(gateway_on):
    from apps.api.routers.agent_mcp import (
        MCP_PROTOCOL_VERSION,
        MCP_SERVER_NAME,
        MCP_SERVER_VERSION,
    )

    try:
        async with _client((_site(), _profile())) as client:
            resp = await client.post(MCP_PATH, json=_rpc("initialize"))
        body = resp.json()
        result = body["result"]
        assert result["protocolVersion"] == MCP_PROTOCOL_VERSION
        assert result["capabilities"] == {"tools": {}}
        assert result["serverInfo"] == {
            "name": MCP_SERVER_NAME,
            "version": MCP_SERVER_VERSION,
        }
        # No internal/version/build-hash leak: only the static site-generic name.
        assert MCP_SERVER_NAME == "beam-agent-concierge"
        # serverInfo carries exactly name + version, nothing dynamic.
        assert set(result["serverInfo"].keys()) == {"name", "version"}
    finally:
        _reset()


# ── AC9b: method allow-list ───────────────────────────────────────────


@pytest.mark.parametrize(
    "method",
    [
        "resources/read",
        "prompts/list",
        # NOTE: "initialize" is now a VALID MCP lifecycle method (WS3) and is
        # covered by test_initialize_returns_static_handshake — it must NOT be in
        # this rejected-methods list anymore.
        "eval",
        "get_visitors",
        "__import__",
        "",
    ],
)
async def test_method_allowlist_rejects_everything_else(gateway_on, method):
    try:
        async with _client((_site(), _profile())) as client:
            resp = await client.post(MCP_PATH, json=_rpc(method))
        body = resp.json()
        assert body["error"]["code"] == -32601
        assert body["error"]["message"] == "Method not found"
        assert "result" not in body
    finally:
        _reset()


async def test_tools_call_with_unknown_tool_name_rejected(gateway_on):
    try:
        async with _client((_site(), _profile())) as client:
            resp = await client.post(
                MCP_PATH, json=_rpc("tools/call", {"name": "drop_table"})
            )
        assert resp.json()["error"]["code"] == -32601
    finally:
        _reset()


# ── AC9b: malformed JSON-RPC error shape ──────────────────────────────


async def test_malformed_json_returns_parse_error(gateway_on):
    try:
        async with _client((_site(), _profile())) as client:
            resp = await client.post(
                MCP_PATH,
                content=b"{not json at all",
                headers={"content-type": "application/json"},
            )
        body = resp.json()
        assert body["jsonrpc"] == "2.0"
        assert body["error"]["code"] == -32700
        assert body["id"] is None
    finally:
        _reset()


@pytest.mark.parametrize(
    "payload",
    [
        [{"jsonrpc": "2.0", "method": "get_offers", "id": 1}],  # batch: unsupported
        {"jsonrpc": "1.0", "method": "get_offers", "id": 1},  # wrong version
        {"method": "get_offers", "id": 1},  # missing jsonrpc
        {"jsonrpc": "2.0", "id": 1},  # missing method
        {"jsonrpc": "2.0", "method": 42, "id": 1},  # non-string method
    ],
)
async def test_invalid_request_shapes_rejected(gateway_on, payload):
    try:
        async with _client((_site(), _profile())) as client:
            resp = await client.post(MCP_PATH, json=payload)
        body = resp.json()
        assert body["error"]["code"] == -32600
        assert body["error"]["message"] == "Invalid Request"
    finally:
        _reset()


async def test_tools_call_with_bad_params_returns_invalid_params(gateway_on):
    try:
        async with _client((_site(), _profile())) as client:
            resp = await client.post(MCP_PATH, json=_rpc("tools/call", "not-an-object"))
        assert resp.json()["error"]["code"] == -32602
    finally:
        _reset()


# ── AC9b: body-size guard ─────────────────────────────────────────────


async def test_oversized_body_rejected_before_parsing(gateway_on):
    """Blob is deliberately valid JSON: rejection must come from the size guard,
    not from the parser choking."""
    blob = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "get_offers", "pad": "A" * (MAX_MCP_BODY_BYTES + 1000)}
    ).encode()
    assert len(blob) > MAX_MCP_BODY_BYTES
    try:
        async with _client((_site(), _profile())) as client:
            resp = await client.post(
                MCP_PATH, content=blob, headers={"content-type": "application/json"}
            )
        assert resp.status_code == 413
    finally:
        _reset()


async def test_oversized_body_rejected_with_forged_content_length(gateway_on):
    """A lying/absent Content-Length must not get a large body into the parser —
    the actual-bytes check is the enforcement, the header is only a fast path."""
    blob = b'{"jsonrpc":"2.0","id":1,"method":"get_offers","pad":"' + b"A" * (
        MAX_MCP_BODY_BYTES + 1000
    ) + b'"}'
    try:
        async with _client((_site(), _profile())) as client:
            resp = await client.post(
                MCP_PATH,
                content=blob,
                headers={"content-type": "application/json", "content-length": "12"},
            )
        assert resp.status_code in (400, 413)
    finally:
        _reset()


async def test_body_just_under_cap_is_accepted(gateway_on):
    payload = {"jsonrpc": "2.0", "id": 1, "method": "get_offers", "pad": "A" * 1000}
    try:
        async with _client((_site(), _profile())) as client:
            resp = await client.post(MCP_PATH, json=payload)
        assert resp.status_code == 200
        assert "result" in resp.json()
    finally:
        _reset()


# ── AC9b: no raw-input echo ───────────────────────────────────────────


async def test_error_responses_never_echo_raw_input(gateway_on):
    marker = "REFLECT-ME-9d2f1a"
    try:
        async with _client((_site(), _profile())) as client:
            responses = [
                await client.post(MCP_PATH, json=_rpc(f"evil_{marker}")),
                await client.post(
                    MCP_PATH, json=_rpc("tools/call", {"name": f"tool_{marker}"})
                ),
                await client.post(
                    MCP_PATH,
                    content=f'{{"broken": "{marker}"'.encode(),
                    headers={"content-type": "application/json"},
                ),
                await client.post(MCP_PATH, json={"jsonrpc": "9.9", "x": marker}),
            ]
        for resp in responses:
            assert marker not in resp.text, f"raw input reflected: {resp.text}"
    finally:
        _reset()


async def test_oversized_request_id_is_not_reflected(gateway_on):
    """The id is the only echoed field; a huge one must degrade to null rather
    than let the caller choose our response body."""
    huge = "B" * 5000
    try:
        async with _client((_site(), _profile())) as client:
            resp = await client.post(MCP_PATH, json=_rpc("nope", request_id=huge))
        body = resp.json()
        assert body["id"] is None
        assert huge not in resp.text
    finally:
        _reset()


async def test_structured_request_id_is_not_reflected(gateway_on):
    try:
        async with _client((_site(), _profile())) as client:
            resp = await client.post(
                MCP_PATH, json=_rpc("nope", request_id={"nested": "PAYLOAD-XYZ"})
            )
        assert resp.json()["id"] is None
        assert "PAYLOAD-XYZ" not in resp.text
    finally:
        _reset()


async def test_normal_scalar_request_id_is_echoed(gateway_on):
    """The guard must not break legitimate JSON-RPC correlation."""
    try:
        async with _client((_site(), _profile())) as client:
            numeric = await client.post(MCP_PATH, json=_rpc("get_offers", request_id=7))
            string = await client.post(
                MCP_PATH, json=_rpc("get_offers", request_id="req-1")
            )
        assert numeric.json()["id"] == 7
        assert string.json()["id"] == "req-1"
    finally:
        _reset()


# ── Rate-limit parity with the REST endpoints ─────────────────────────


def test_mcp_route_is_rate_limited():
    """E3: this is the only body-accepting route in Phase 1+2 scope; leaving it
    unrated would make it the cheapest way to hammer the gateway."""
    import inspect

    from apps.api.routers import agent_gateway as rest_router
    from apps.api.routers import agent_mcp as mcp_router

    mcp_src = inspect.getsource(mcp_router)
    assert "@limiter.limit(" in mcp_src
    assert mcp_router.MCP_RATE_LIMIT == rest_router.PUBLIC_READ_LIMIT
