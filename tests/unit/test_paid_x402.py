"""InFlow x402 seller — /api/v1/paid/* payment gate.

Exercises the REAL InFlow SDK (Seller + Facilitator) and the REAL upstream
x402 HTTP resource server end to end; only the InFlow HTTP API is faked (an
``httpx.MockTransport`` passed via ``ClientOptions(transport=...)``) and the
``paid_requests`` table is swapped for an in-memory store. No PostgreSQL,
Redis or network. Unit lane.
"""

import base64
import json

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import apps.api.main  # noqa: F401 — registers every ORM model
from apps.api.config import settings
from apps.api.routers import paid as paid_router
from apps.api.services import x402_seller
from apps.api.services.rate_limiter import limiter
from apps.api.services.x402_seller import (
    CachedPaidResponse,
    build_gate,
    redact_payment_headers,
    set_gate,
)

pytestmark = pytest.mark.unit

from inflowpay import ClientOptions  # noqa: E402
from x402.http.utils import encode_payment_signature_header  # noqa: E402
from x402.schemas import PaymentPayload, PaymentRequirements  # noqa: E402

DETECT = "/api/v1/paid/detect-platform"


# ─── Fakes ──────────────────────────────────────────────────────────────────


class FakeInflow:
    """Minimal fake of the InFlow x402 seller/facilitator HTTP API."""

    def __init__(self) -> None:
        self.verify_valid = True
        self.settle_mode = "ok"  # ok | fail | pending_then_ok | error
        self.calls: dict[str, int] = {}
        self.api_keys: set[str] = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls[path] = self.calls.get(path, 0) + 1
        self.api_keys.add(request.headers.get("x-api-key", ""))
        if path == "/v1/x402/config":
            return httpx.Response(200, json={
                "sellerId": "sel_test",
                # An asset gives the USD price its settlement currency; with no
                # wallet it yields no on-chain `exact` offer — balance only.
                "assets": [{
                    "assetId": "USDC", "assetName": "USDC", "currency": "USDC",
                    "blockchain": "base", "network": "eip155:8453", "decimals": 6,
                }],
                "wallets": [],
                "paymentMethods": [{
                    "scheme": "balance", "network": "inflow:1", "payTo": "sel_test",
                    "decimals": 6, "extra": {},
                }],
                "supported": [{"x402Version": 2, "scheme": "balance", "network": "inflow:1"}],
            })
        if path == "/v1/x402/supported":
            return httpx.Response(200, json={
                "kinds": [{"x402Version": 2, "scheme": "balance", "network": "inflow:1"}],
                "extensions": [],
                "signers": {},
            })
        body = json.loads(request.content or b"{}")
        assert body.get("x402Version") == 2 and "paymentPayload" in body and "paymentRequirements" in body
        if path == "/v1/x402/verify":
            if self.verify_valid:
                return httpx.Response(200, json={"isValid": True, "payer": "buyer_1"})
            return httpx.Response(
                200, json={"isValid": False, "invalidReason": "insufficient_funds", "payer": "buyer_1"}
            )
        if path == "/v1/x402/settle":
            if self.settle_mode == "pending_then_ok" and self.calls[path] == 1:
                return httpx.Response(
                    409, headers={"retry-after": "0"},
                    json={"errorReason": "idempotency_pending", "message": "pending"},
                )
            if self.settle_mode == "fail":
                return httpx.Response(200, json={
                    "success": False, "errorReason": "insufficient_funds",
                    "transaction": "", "network": "inflow:1", "payer": "buyer_1",
                })
            if self.settle_mode == "error":
                return httpx.Response(500, json={"message": "boom"})
            return httpx.Response(200, json={
                "success": True, "transaction": "tx_123", "network": "inflow:1", "payer": "buyer_1",
            })
        return httpx.Response(404, json={"message": "unknown"})


class MemoryStore:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    async def get_settled(self, payment_hash):
        row = self.rows.get(payment_hash)
        if row and row["status"] == "settled":
            return CachedPaidResponse(
                row["response_status"], row["response_body"], row["payment_response_header"]
            )
        return None

    async def claim(self, payment_hash, route_id):
        row = self.rows.get(payment_hash)
        if row is None:
            self.rows[payment_hash] = {"status": "pending", "route_id": route_id}
            return "claimed"
        if row["status"] in ("handler_failed", "settle_failed"):
            row["status"] = "pending"
            return "claimed"
        return "settled" if row["status"] == "settled" else "in_flight"

    async def mark_failed(self, payment_hash, status, reason):
        self.rows[payment_hash].update(status=status, error_reason=reason)

    async def mark_settled(self, payment_hash, **fields):
        self.rows[payment_hash].update(status="settled", **fields)


# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def fake_inflow():
    return FakeInflow()


@pytest.fixture
def upstream(monkeypatch):
    calls = {"n": 0, "raise": False}

    async def fake_detect(url):
        calls["n"] += 1
        if calls["raise"]:
            raise RuntimeError("site unreachable")
        return {"platform": "shopify", "confidence": 0.9, "has_gtm": False, "gtm_id": None}

    monkeypatch.setattr(paid_router, "detect_platform", fake_detect)
    return calls


@pytest.fixture
async def client(monkeypatch, fake_inflow, upstream):
    monkeypatch.setattr(settings, "inflow_x402_enabled", True)
    limiter.enabled = False
    options = ClientOptions(
        environment="sandbox", api_key="sk_test_fake", transport=httpx.MockTransport(fake_inflow)
    )
    store = MemoryStore()
    gate = await build_gate(options, store)
    set_gate(gate)
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(paid_router.router, prefix="/api/v1/paid")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.store = store  # type: ignore[attr-defined]
        yield c
    await x402_seller.teardown_gate()
    limiter.enabled = True


def _decode(value: str) -> dict:
    return json.loads(base64.b64decode(value))


async def _signed_header(client, signature: str = "sig-1") -> str:
    resp = await client.post(DETECT, json={"url": "https://example.com"})
    required = _decode(resp.headers["PAYMENT-REQUIRED"])
    accepted = PaymentRequirements.model_validate(required["accepts"][0])
    payload = PaymentPayload(x402_version=2, payload={"signature": signature}, accepted=accepted)
    return encode_payment_signature_header(payload)


# ─── Tests ──────────────────────────────────────────────────────────────────


async def test_no_payment_returns_402_with_requirements(client, upstream):
    resp = await client.post(DETECT, json={"url": "https://example.com"})
    assert resp.status_code == 402
    required = _decode(resp.headers["PAYMENT-REQUIRED"])
    assert required["x402Version"] == 2
    accept = required["accepts"][0]
    assert accept["scheme"] == "balance"
    assert accept["network"] == "inflow:1"
    assert accept["amount"] == "10000"  # $0.01 at 6 decimals
    assert accept["payTo"] == "sel_test"
    # body mirrors the header for body-only readers
    assert resp.json()["accepts"][0]["scheme"] == "balance"
    assert upstream["n"] == 0


async def test_route_prices_differ_per_route(client):
    resp = await client.post("/api/v1/paid/company-from-domain", json={"domain": "stripe.com"})
    assert resp.status_code == 402
    assert _decode(resp.headers["PAYMENT-REQUIRED"])["accepts"][0]["amount"] == "50000"


async def test_invalid_input_rejected_before_payment(client, fake_inflow):
    resp = await client.post("/api/v1/paid/company-from-domain", json={"domain": "not a domain"})
    assert resp.status_code == 422
    assert "/v1/x402/verify" not in fake_inflow.calls


async def test_verify_failure_returns_402_and_no_handler(client, fake_inflow, upstream):
    header = await _signed_header(client)
    fake_inflow.verify_valid = False
    resp = await client.post(DETECT, json={"url": "https://example.com"}, headers={"PAYMENT-SIGNATURE": header})
    assert resp.status_code == 402
    assert "PAYMENT-REQUIRED" in resp.headers
    assert upstream["n"] == 0
    assert "/v1/x402/settle" not in fake_inflow.calls


async def test_happy_path_verify_handler_settle(client, fake_inflow, upstream):
    header = await _signed_header(client)
    resp = await client.post(DETECT, json={"url": "https://example.com"}, headers={"PAYMENT-SIGNATURE": header})
    assert resp.status_code == 200, resp.text
    assert resp.json()["platform"] == "shopify"
    receipt = _decode(resp.headers["PAYMENT-RESPONSE"])
    assert receipt["success"] is True and receipt["transaction"] == "tx_123"
    assert fake_inflow.calls["/v1/x402/verify"] == 1
    assert fake_inflow.calls["/v1/x402/settle"] == 1
    assert fake_inflow.api_keys == {"sk_test_fake"}
    assert upstream["n"] == 1
    (row,) = client.store.rows.values()
    assert row["status"] == "settled"
    assert row["transaction"] == "tx_123" and row["amount"] == "10000"
    assert row["network"] == "inflow:1" and row["payer"] == "buyer_1"
    assert row["route_id"] == "detect-platform"


async def test_v1_x_payment_header_is_not_a_payment(client, fake_inflow, upstream):
    # InFlow is x402 v2-only; the v1 X-PAYMENT header is ignored => 402, nothing served.
    header = await _signed_header(client)
    resp = await client.post(DETECT, json={"url": "https://example.com"}, headers={"X-PAYMENT": header})
    assert resp.status_code == 402
    assert upstream["n"] == 0
    assert "/v1/x402/verify" not in fake_inflow.calls


async def test_handler_error_does_not_settle(client, fake_inflow, upstream):
    upstream["raise"] = True
    header = await _signed_header(client)
    resp = await client.post(DETECT, json={"url": "https://example.com"}, headers={"PAYMENT-SIGNATURE": header})
    assert resp.status_code == 502
    assert "/v1/x402/settle" not in fake_inflow.calls
    (row,) = client.store.rows.values()
    assert row["status"] == "handler_failed"
    # Same payment may be retried once the upstream recovers.
    upstream["raise"] = False
    resp = await client.post(DETECT, json={"url": "https://example.com"}, headers={"PAYMENT-SIGNATURE": header})
    assert resp.status_code == 200
    assert fake_inflow.calls["/v1/x402/settle"] == 1


async def test_settle_409_pending_is_retried(client, fake_inflow):
    fake_inflow.settle_mode = "pending_then_ok"
    header = await _signed_header(client)
    resp = await client.post(DETECT, json={"url": "https://example.com"}, headers={"PAYMENT-SIGNATURE": header})
    assert resp.status_code == 200
    assert fake_inflow.calls["/v1/x402/settle"] == 2
    assert _decode(resp.headers["PAYMENT-RESPONSE"])["success"] is True


@pytest.mark.parametrize("mode", ["fail", "error"])
async def test_settle_failure_returns_402_and_logs_loss(client, fake_inflow, upstream, mode):
    fake_inflow.settle_mode = mode
    header = await _signed_header(client)
    resp = await client.post(DETECT, json={"url": "https://example.com"}, headers={"PAYMENT-SIGNATURE": header})
    assert resp.status_code == 402
    assert "shopify" not in resp.text  # content withheld when unpaid
    assert _decode(resp.headers["PAYMENT-RESPONSE"])["success"] is False
    (row,) = client.store.rows.values()
    assert row["status"] == "settle_failed"


async def test_replay_returns_cached_without_upstream_or_settle(client, fake_inflow, upstream):
    header = await _signed_header(client)
    first = await client.post(DETECT, json={"url": "https://example.com"}, headers={"PAYMENT-SIGNATURE": header})
    second = await client.post(DETECT, json={"url": "https://example.com"}, headers={"PAYMENT-SIGNATURE": header})
    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()
    assert second.headers["PAYMENT-RESPONSE"] == first.headers["PAYMENT-RESPONSE"]
    assert upstream["n"] == 1
    assert fake_inflow.calls["/v1/x402/verify"] == 1
    assert fake_inflow.calls["/v1/x402/settle"] == 1


async def test_in_flight_duplicate_gets_409(client, upstream):
    header = await _signed_header(client)
    phash = x402_seller.payment_hash(header)
    client.store.rows[phash] = {"status": "pending", "route_id": "detect-platform"}
    resp = await client.post(DETECT, json={"url": "https://example.com"}, headers={"PAYMENT-SIGNATURE": header})
    assert resp.status_code == 409
    assert upstream["n"] == 0


async def test_gate_missing_returns_503(client):
    set_gate(None)
    resp = await client.post(DETECT, json={"url": "https://example.com"})
    assert resp.status_code == 503


async def test_runtime_flag_off_returns_404(client, monkeypatch):
    monkeypatch.setattr(settings, "inflow_x402_enabled", False)
    resp = await client.post(DETECT, json={"url": "https://example.com"})
    assert resp.status_code == 404


async def test_main_app_does_not_mount_paid_routes_when_flag_off():
    assert settings.inflow_x402_enabled is False  # default
    from apps.api.main import app

    assert not any(getattr(r, "path", "").startswith("/api/v1/paid") for r in app.routes)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(DETECT, json={"url": "https://example.com"})
    assert resp.status_code == 404


async def test_setup_gate_noop_without_flag_or_key(monkeypatch):
    monkeypatch.setattr(settings, "inflow_x402_enabled", False)
    assert await x402_seller.setup_gate() is None
    monkeypatch.setattr(settings, "inflow_x402_enabled", True)
    monkeypatch.setattr(settings, "inflow_api_key", "")
    assert await x402_seller.setup_gate() is None


def test_redact_payment_headers():
    out = redact_payment_headers({
        "X-PAYMENT": "abc", "payment-signature": "def", "PAYMENT-RESPONSE": "ghi",
        "x-payment-response": "jkl", "user-agent": "agent/1.0",
    })
    assert out == {
        "X-PAYMENT": "***", "payment-signature": "***", "PAYMENT-RESPONSE": "***",
        "x-payment-response": "***", "user-agent": "agent/1.0",
    }


async def test_request_log_middleware_redacts_payment_headers(monkeypatch):
    from apps.api import main as main_mod
    from apps.api.main import app

    captured: dict = {}

    async def fake_persist(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(settings, "request_log_enabled", True)
    monkeypatch.setattr(main_mod.request_logger, "should_log", lambda *a, **k: "test")
    monkeypatch.setattr(main_mod.request_logger, "is_excluded", lambda path: False)
    monkeypatch.setattr(main_mod.request_logger, "persist_log", fake_persist)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post(
            DETECT, json={"url": "https://example.com"},
            headers={"X-PAYMENT": "secret-payload", "PAYMENT-SIGNATURE": "secret-sig"},
        )
    import asyncio

    for _ in range(5):
        if captured:
            break
        await asyncio.sleep(0)
    headers = captured["headers"]
    assert headers["x-payment"] == "***"
    assert headers["payment-signature"] == "***"
    assert "secret" not in json.dumps(headers)
