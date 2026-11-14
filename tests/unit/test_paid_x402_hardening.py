"""x402 seller hardening: ledger safety, purged replays, in-flight cap, 402 body."""
import json
from types import SimpleNamespace

import pytest

from apps.api.services import x402_seller as xs

pytestmark = pytest.mark.unit


class _Redis:
    def __init__(self):
        self.n: dict[str, int] = {}

    async def incr(self, k):
        self.n[k] = self.n.get(k, 0) + 1
        return self.n[k]

    async def decr(self, k):
        self.n[k] = self.n.get(k, 0) - 1
        return self.n[k]

    async def expire(self, k, ttl):
        return True


async def test_safe_ledger_swallows_db_error():
    async def boom():
        raise RuntimeError("db down")

    await xs._safe_ledger("r", "abcdef0123456789", "mark_settled", boom())  # no raise


def test_cached_response_purged_body_is_410():
    resp = xs._cached_response(xs.CachedPaidResponse(200, None, "hdr"))
    assert resp.status_code == 410
    assert resp.headers["PAYMENT-RESPONSE"] == "hdr"


def test_cached_response_replays_body():
    resp = xs._cached_response(xs.CachedPaidResponse(200, {"ok": 1}, None))
    assert resp.status_code == 200
    assert json.loads(resp.body) == {"ok": 1}


async def test_inflight_cap(monkeypatch):
    import apps.api.services.redis_client as rc

    r = _Redis()
    monkeypatch.setattr(rc, "get_redis", lambda: r)
    monkeypatch.setattr(xs.settings, "paid_max_inflight_per_payer", 2)
    assert await xs._acquire_slot("k") is True
    assert await xs._acquire_slot("k") is True
    assert await xs._acquire_slot("k") is False
    assert r.n["k"] == 2  # rejected attempt rolled back
    await xs._release_slot("k")
    assert await xs._acquire_slot("k") is True


async def test_inflight_cap_fails_open_without_redis(monkeypatch):
    import apps.api.services.redis_client as rc

    def boom():
        raise ConnectionError("down")

    monkeypatch.setattr(rc, "get_redis", boom)
    assert await xs._acquire_slot("k") is None


def test_payer_key_prefers_signed_payer_and_hashes_it():
    req = SimpleNamespace()
    res = SimpleNamespace(payment_payload=SimpleNamespace(payload={"authorization": {"from": "0xAB"}}))
    res2 = SimpleNamespace(payment_payload=SimpleNamespace(payload={"payer": "0xab"}))
    k = xs._payer_key(res, req)
    assert k == xs._payer_key(res2, req)
    assert "0xab" not in k.lower()


def test_402_body_gets_accepts_when_sdk_body_lacks_it():
    instr = SimpleNamespace(is_html=False, body={"error": "payment required"}, status=402, headers={})
    resp = xs._instructions_to_response(instr, fallback_body={"accepts": [{"scheme": "balance"}]})
    body = json.loads(resp.body)
    assert body["accepts"][0]["scheme"] == "balance"
    assert body["error"] == "payment required"
