"""G2 — Meta lookalike payload + error surfacing (closed-won-lookalikes)."""

import json
from types import SimpleNamespace

import httpx
import pytest

from apps.api.config import settings
from apps.api.services.ads import meta
from apps.api.services.ads.base import LookalikeSpec

pytestmark = pytest.mark.unit

SPEC = LookalikeSpec(country="US", ratio=0.05)


def test_should_build_meta_lookalike_payload_with_country_while_version_le_v26():
    body = meta.build_meta_lookalike_payload("seed-1", SPEC, version="v25.0")
    assert body["subtype"] == "LOOKALIKE"
    assert body["origin_audience_id"] == "seed-1"
    spec = json.loads(body["lookalike_spec"])
    assert spec["ratio"] == 0.05 and spec["country"] == "US"
    assert json.loads(meta.build_meta_lookalike_payload("s", SPEC, version="v26.0")["lookalike_spec"])["country"] == "US"


def test_country_omitted_after_v26():
    spec = json.loads(meta.build_meta_lookalike_payload("s", SPEC, version="v27.0")["lookalike_spec"])
    assert "country" not in spec


def test_pinned_version_still_sends_country():
    assert meta.graph_major_version() <= 26


def test_small_seed_warning():
    assert "at least" in meta.meta_seed_warning(settings.meta_lookalike_min_seed - 1)
    assert meta.meta_seed_warning(settings.meta_lookalike_min_seed) == ""


async def test_mock_create_returns_id(monkeypatch):
    monkeypatch.setattr(settings, "mock_external_apis", True)
    res = await meta.MetaAdsProvider().create_lookalike(SimpleNamespace(), "seed", SPEC)
    assert res.status == "created" and res.audience_id.startswith("mock-meta-lal-")


async def test_provider_error_is_surfaced(monkeypatch):
    monkeypatch.setattr(settings, "mock_external_apis", False)
    monkeypatch.setattr(meta, "_access_token", lambda c: "tok")
    monkeypatch.setattr(meta, "_account_path", lambda c: "act_1")

    def handler(request):
        return httpx.Response(
            400, json={"error": {"message": "Source audience is too small", "code": 2654}}
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        meta.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    res = await meta.MetaAdsProvider().create_lookalike(SimpleNamespace(), "seed", SPEC)
    assert res.status == "error"
    assert "too small" in res.error
