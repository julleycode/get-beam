"""Unit tests for the paid reseller Apollo path (services/reseller_apollo.py) and
its wiring into the enricher's Apollo step.

No network: httpx runs over a MockTransport that asserts the exact request
apps/web's buy route expects; Redis is fakeredis (real INCRBY/DECRBY semantics).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import httpx
import pytest

import apps.api.main  # noqa: F401 — registers ORM mappers before model construction
from apps.api.config import settings
from apps.api.services import reseller_apollo
from apps.api.services.enricher import Enricher, map_apollo_person

pytestmark = pytest.mark.unit

EMAIL = "chris@dvrk.vn"
SECRET = "test-internal-secret-not-real"
BASE = "http://web.test"

PERSON = {
    "name": "Chris Nguyen",
    "title": "Founder",
    "seniority": "founder",
    "linkedin_url": "https://linkedin.com/in/chrisn",
    "twitter_url": "https://twitter.com/chrisn",
    "city": "Ho Chi Minh City",
    "country": "Vietnam",
    "organization": {
        "name": "DVRK",
        "primary_domain": "dvrk.vn",
        "industry": "design",
        "estimated_num_employees": 12,
    },
}


def _paid_body(person: dict | None = PERSON, amount: str = "0.038") -> dict:
    return {
        "provider": "locus_apollo",
        "protocol": "x402",
        "amount_usd": amount,
        "transaction": "0xsettled",
        "data": {"person": person} if person is not None else {},
    }


@pytest.fixture
def redis(monkeypatch):
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(reseller_apollo, "get_redis", lambda: fake)
    return fake


@pytest.fixture
def logged(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(reseller_apollo, "log_api_call", mock)
    return mock


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "reseller_apollo_enabled", True)
    monkeypatch.setattr(settings, "apollo_api_key", "")
    monkeypatch.setattr(settings, "mock_external_apis", False)
    monkeypatch.setattr(settings, "beam_web_internal_base", BASE + "/")
    monkeypatch.setattr(settings, "internal_paid_api_secret", SECRET)
    monkeypatch.setattr(settings, "reseller_daily_budget_usd", 1.00)
    monkeypatch.setattr(settings, "reseller_max_price_usd", 0.05)


class Upstream:
    """MockTransport handler for apps/web's /api/internal/buy/apollo-person."""

    def __init__(self, status: int = 200, body: object = None, exc: Exception | None = None):
        self.status = status
        self.body = _paid_body() if body is None else body
        self.exc = exc
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.exc is not None:
            raise self.exc
        return httpx.Response(self.status, json=self.body)


@pytest.fixture
def upstream(monkeypatch):
    def install(handler: Upstream) -> Upstream:
        real = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real(*args, **kwargs)

        monkeypatch.setattr(reseller_apollo.httpx, "AsyncClient", factory)
        return handler

    return install


async def _spent(redis) -> int:
    return int(await redis.get(reseller_apollo.spend_key()) or 0)


# ─────────────────────────────── gates ───────────────────────────────


@pytest.mark.usefixtures("configured")
class TestGates:
    @pytest.mark.parametrize(
        "attr,value",
        [
            ("reseller_apollo_enabled", False),
            ("apollo_api_key", "direct-key"),  # direct key present → never the reseller
            ("beam_web_internal_base", ""),
            ("internal_paid_api_secret", ""),
        ],
    )
    async def test_closed_gate_makes_no_call_and_reserves_nothing(
        self, monkeypatch, redis, logged, upstream, attr, value
    ):
        monkeypatch.setattr(settings, attr, value)
        handler = upstream(Upstream())
        assert await reseller_apollo.enrich_via_reseller(EMAIL) is None
        assert handler.requests == []
        assert await _spent(redis) == 0
        logged.assert_not_awaited()

    async def test_mock_mode_is_deterministic_and_offline(self, monkeypatch, redis, logged, upstream):
        monkeypatch.setattr(settings, "mock_external_apis", True)
        monkeypatch.setattr(settings, "beam_web_internal_base", "")
        handler = upstream(Upstream())
        first = await reseller_apollo.enrich_via_reseller(EMAIL)
        assert first == await reseller_apollo.enrich_via_reseller(EMAIL)
        assert first["company_domain"] == "dvrk.vn"
        assert handler.requests == []
        assert await _spent(redis) == 0


# ─────────────────────────────── call + budget ───────────────────────────────


@pytest.mark.usefixtures("configured")
class TestPaidCall:
    async def test_request_shape_is_exact_and_carries_no_reveal_flags(self, redis, logged, upstream):
        handler = upstream(Upstream())
        await reseller_apollo.enrich_via_reseller(EMAIL, site_id="site_x", visitor_id="v1")
        assert len(handler.requests) == 1
        req = handler.requests[0]
        assert str(req.url) == f"{BASE}/api/internal/buy/apollo-person"
        assert req.method == "POST"
        assert req.headers["x-beam-internal-secret"] == SECRET
        assert json.loads(req.content) == {"email": EMAIL}
        assert b"reveal" not in req.content

    async def test_success_maps_like_direct_apollo_and_trims_reservation(self, redis, logged, upstream):
        upstream(Upstream())
        data = await reseller_apollo.enrich_via_reseller(EMAIL, site_id="site_x", visitor_id="v1")
        assert data == map_apollo_person(PERSON)
        assert data["company_size"] == "12"
        assert await _spent(redis) == 38_000  # micro-USD: reservation trimmed to the real price
        kwargs = logged.await_args.kwargs
        assert kwargs["provider"] == "locus_apollo"
        assert kwargs["cost_usd"] == pytest.approx(0.038)
        assert kwargs["success"] is True
        assert kwargs["site_id"] == "site_x"
        assert EMAIL not in json.dumps(kwargs, default=str)

    async def test_parity_with_direct_apollo_parser(self, monkeypatch, redis, logged, upstream):
        """The reseller path must produce the SAME dict _enrich_apollo does."""
        upstream(Upstream())
        via_reseller = await reseller_apollo.enrich_via_reseller(EMAIL)

        monkeypatch.setattr(settings, "apollo_api_key", "test-key")
        monkeypatch.setattr(settings, "apollo_enabled", True)
        e = Enricher(db=AsyncMock())
        e._log_enrich = AsyncMock()
        e._cache_get = AsyncMock(return_value=(False, None))
        e._cache_set = AsyncMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"person": PERSON}
        client = AsyncMock()
        client.post.return_value = resp
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=client)
        cm.__aexit__ = AsyncMock(return_value=False)
        with patch("apps.api.services.enricher.httpx.AsyncClient", return_value=cm):
            direct = await e._enrich_apollo(EMAIL, visitor=None)
        assert via_reseller == direct

    async def test_paid_empty_person_is_a_no_match(self, redis, logged, upstream):
        upstream(Upstream(body=_paid_body(person=None)))
        result = await reseller_apollo.purchase_apollo_person(EMAIL)
        assert result.outcome == "no_match"
        assert await _spent(redis) == 38_000

    async def test_over_budget_skips_without_calling(self, redis, logged, upstream):
        await redis.set(reseller_apollo.spend_key(), 980_000)  # $0.98 already used
        handler = upstream(Upstream())
        result = await reseller_apollo.purchase_apollo_person(EMAIL)
        assert result.outcome == "skipped"
        assert handler.requests == []
        assert await _spent(redis) == 980_000

    async def test_budget_allows_exactly_up_to_the_cap(self, redis, logged, upstream):
        await redis.set(reseller_apollo.spend_key(), 950_000)
        upstream(Upstream(body=_paid_body(amount="0.05")))
        assert (await reseller_apollo.purchase_apollo_person(EMAIL)).outcome == "match"
        assert await _spent(redis) == 1_000_000

    async def test_redis_down_fails_closed(self, monkeypatch, logged, upstream):
        def broken():
            raise ConnectionError("redis down")

        monkeypatch.setattr(reseller_apollo, "get_redis", broken)
        handler = upstream(Upstream())
        assert (await reseller_apollo.purchase_apollo_person(EMAIL)).outcome == "skipped"
        assert handler.requests == []

    @pytest.mark.parametrize(
        "status,body,spent,outcome",
        [
            (402, {"error": "price_above_cap"}, 0, "skipped"),
            (402, {"error": "no_payable_offer"}, 0, "skipped"),
            (402, {"error": "payment_pending_or_declined"}, 0, "failed"),
            (502, {"error": "upstream_error", "paid": False}, 0, "failed"),
            (502, {"error": "upstream_error", "paid": True}, 50_000, "failed"),
            (502, {"error": "upstream_error", "paid": None}, 50_000, "failed"),
            (404, {"error": "not_found"}, 0, "failed"),
            (503, {"error": "unavailable"}, 0, "failed"),
            (200, _paid_body(amount="not-a-number"), 50_000, "match"),
        ],
    )
    async def test_reconcile_releases_only_when_clearly_unpaid(
        self, redis, logged, upstream, status, body, spent, outcome
    ):
        handler = upstream(Upstream(status=status, body=body))
        result = await reseller_apollo.purchase_apollo_person(EMAIL)
        assert result.outcome == outcome
        assert await _spent(redis) == spent
        assert len(handler.requests) == 1  # never retried

    async def test_timeout_keeps_full_reservation_and_does_not_retry(self, redis, logged, upstream):
        handler = upstream(Upstream(exc=httpx.ReadTimeout("slow")))
        result = await reseller_apollo.purchase_apollo_person(EMAIL)
        assert result.outcome == "failed"
        assert result.paid is None
        assert await _spent(redis) == 50_000
        assert len(handler.requests) == 1
        logged.assert_awaited_once()


# ─────────────────────────────── enricher wiring ───────────────────────────────


def _visitor():
    v = MagicMock()
    v.visitor_id = "visitor_abcdef123"
    v.site_id = "site_x"
    v.enrichment_status = "pending"
    return v


@pytest.mark.asyncio
class TestEnricherWiring:
    @pytest.fixture(autouse=True)
    def _gates(self, monkeypatch):
        import apps.api.services.known_contacts_match as kcm

        monkeypatch.setattr(kcm, "is_known_contact", AsyncMock(return_value=(False, None)))
        monkeypatch.setattr(settings, "people_data_labs_api_key", "test-key")

    def _enricher(self):
        e = Enricher(db=AsyncMock())
        e._enrich_pdl = AsyncMock(return_value=None)
        e._enrich_apollo = AsyncMock(return_value=None)
        e._enrich_apollo_reseller = AsyncMock(return_value={"job_title": "Founder"})
        e._upsert_profile = AsyncMock(
            return_value=MagicMock(linkedin_url=None, twitter_handle=None, social_context=None, avatar_url="set")
        )
        e._fetch_and_store_content = AsyncMock()
        e._profile_completeness = MagicMock(return_value=0.5)
        return e

    def _identified(self):
        ident = MagicMock()
        ident.email = EMAIL
        return ident

    async def test_reseller_replaces_apollo_when_key_absent_and_flag_on(self, monkeypatch):
        monkeypatch.setattr(settings, "apollo_api_key", "")
        monkeypatch.setattr(settings, "reseller_apollo_enabled", True)
        e = self._enricher()
        await e.enrich_tier1(_visitor(), self._identified())
        e._enrich_apollo_reseller.assert_awaited_once()
        e._enrich_apollo.assert_not_awaited()
        assert e._upsert_profile.await_args.args[1] == {"job_title": "Founder"}

    @pytest.mark.parametrize("key,flag", [("direct-key", True), ("", False), ("direct-key", False)])
    async def test_direct_apollo_otherwise(self, monkeypatch, key, flag):
        monkeypatch.setattr(settings, "apollo_api_key", key)
        monkeypatch.setattr(settings, "reseller_apollo_enabled", flag)
        e = self._enricher()
        await e.enrich_tier1(_visitor(), self._identified())
        e._enrich_apollo.assert_awaited_once()
        e._enrich_apollo_reseller.assert_not_awaited()

    async def test_reseller_not_called_when_pdl_hits(self, monkeypatch):
        monkeypatch.setattr(settings, "apollo_api_key", "")
        monkeypatch.setattr(settings, "reseller_apollo_enabled", True)
        e = self._enricher()
        e._enrich_pdl = AsyncMock(return_value={"job_title": "VP"})
        await e.enrich_tier1(_visitor(), self._identified())
        e._enrich_apollo_reseller.assert_not_awaited()


@pytest.mark.asyncio
class TestResellerCache:
    def _enricher(self):
        e = Enricher(db=AsyncMock())
        e._cache_set = AsyncMock()
        return e

    async def test_cache_hit_never_buys(self, monkeypatch):
        buy = AsyncMock()
        monkeypatch.setattr(reseller_apollo, "purchase_apollo_person", buy)
        e = self._enricher()
        e._cache_get = AsyncMock(return_value=(True, {"job_title": "CTO"}))
        assert await e._enrich_apollo_reseller(EMAIL, visitor=_visitor()) == {"job_title": "CTO"}
        buy.assert_not_awaited()

    async def test_negative_cache_hit_never_buys(self, monkeypatch):
        buy = AsyncMock()
        monkeypatch.setattr(reseller_apollo, "purchase_apollo_person", buy)
        e = self._enricher()
        e._cache_get = AsyncMock(return_value=(True, None))
        assert await e._enrich_apollo_reseller(EMAIL, visitor=_visitor()) is None
        buy.assert_not_awaited()

    @pytest.mark.parametrize(
        "outcome,data,cached",
        [
            ("match", {"job_title": "Founder"}, [{"job_title": "Founder"}]),
            ("no_match", None, [None]),
            ("skipped", None, []),
            ("failed", None, []),
        ],
    )
    async def test_only_definitive_answers_are_cached(self, monkeypatch, outcome, data, cached):
        monkeypatch.setattr(
            reseller_apollo,
            "purchase_apollo_person",
            AsyncMock(return_value=reseller_apollo.ResellerResult(outcome, data)),
        )
        e = self._enricher()
        e._cache_get = AsyncMock(return_value=(False, None))
        assert await e._enrich_apollo_reseller(EMAIL, visitor=_visitor()) == data
        assert [c.args[1] for c in e._cache_set.await_args_list] == cached
        # Shares the direct Apollo cache key.
        for c in e._cache_set.await_args_list:
            assert c.args[0].startswith("enrich:apollo:")
