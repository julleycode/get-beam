"""G1 + G6 — on-site greeting eligibility (apps/api/services/greeting.py).

No DB / Redis: a scripted fake session answers the two SELECTs (site, visitor)
and a dict-backed fake Redis stands in for the cache. Every live/paid provider
path is monkeypatched to RAISE, so any accidental call fails the test.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pytest

import apps.api.services.company_resolver as company_resolver
import apps.api.services.greeting as g
from apps.api.config import settings

pytestmark = pytest.mark.unit

PUBLIC_IP = "198.51.100.7"
MOCK_IP = "203.0.113.5"


class _Result:
    def __init__(self, value):
        self._v = value

    def scalar_one_or_none(self):
        return self._v

    def first(self):
        return self._v


class FakeDB:
    """execute(): 1st call → site row; subsequent calls → visitor flags by vid."""

    def __init__(self, site, visitors=None):
        self.site = site
        self.visitors = visitors or {}
        self.calls = 0
        self.vid = None

    async def execute(self, stmt):
        self.calls += 1
        if self.calls == 1:
            return _Result(self.site)
        return _Result(self.visitors.get(self.vid))

    async def rollback(self):
        pass


class FakeRedis:
    def __init__(self, data=None):
        self.data = dict(data or {})
        self.sets: list[str] = []

    async def get(self, k):
        return self.data.get(k)

    async def set(self, k, v, ex=None):
        self.sets.append(k)
        self.data[k] = v


def _site(**kw):
    base = dict(
        site_id="site_acme",
        url="https://www.customer.com",
        greeting_enabled=True,
        greeting_templates=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


ORG = {"org_name": "Globex Corp", "domain": "globex.com", "asn": 1, "org_kind": "org"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "onsite_greeting_enabled", True)
    monkeypatch.setattr(settings, "mock_external_apis", False)

    def _boom(*a, **k):
        raise AssertionError("greeting must never call a live/paid provider")

    async def _aboom(*a, **k):
        raise AssertionError("greeting must never call a live/paid provider")

    for name in ("resolve_company_cached", "check_ip_privacy", "resolve_company_from_ip",
                 "is_datacenter_ip", "_resolve_via_local_ip_org"):
        monkeypatch.setattr(company_resolver, name, _aboom)
    import httpx

    monkeypatch.setattr(httpx.AsyncClient, "send", _aboom)
    monkeypatch.setattr(httpx, "get", _boom)

    calls = {"n": 0}

    async def _lookup(db, ip):
        calls["n"] += 1
        return dict(ORG)

    monkeypatch.setattr(g, "lookup_ip_org", _lookup)
    return calls


async def _decide(db, redis=None, ip=PUBLIC_IP, origin="https://customer.com", vid=None, site_id="site_acme"):
    db.vid = vid
    return await g.decide_greeting(db, redis if redis is not None else FakeRedis(), site_id, ip, origin, vid)


# ── happy path + flags ─────────────────────────────────────────────────────

async def test_shows_for_org_with_allow_listed_keys():
    show, reason, payload = await _decide(FakeDB(_site()))
    assert show is True and reason == "shown"
    assert set(payload) == {"show", "template_id", "text", "cta_url"}
    assert payload["text"] == "Welcome, Globex Corp team!"
    assert payload["cta_url"] is None


async def test_global_flag_off(monkeypatch):
    monkeypatch.setattr(settings, "onsite_greeting_enabled", False)
    db = FakeDB(_site())
    show, reason, payload = await _decide(db)
    assert (show, reason, payload) == (False, "flag_off", {"show": False})
    assert db.calls == 0


async def test_site_flag_off():
    assert (await _decide(FakeDB(_site(greeting_enabled=False))))[1] == "site_off"


async def test_unknown_site():
    show, reason, payload = await _decide(FakeDB(None))
    assert (show, reason, payload) == (False, "unknown_site", {"show": False})


# ── Origin normalization ───────────────────────────────────────────────────

@pytest.mark.parametrize(
    "site_url,origin,ok",
    [
        ("customer.com", "https://customer.com", True),            # schemeless Site.url
        ("https://www.customer.com", "https://CUSTOMER.com", True),  # case + www
        ("https://customer.com:8443/x", "https://customer.com:3000", True),  # ports
        ("https://customer.com", "https://www.customer.com", True),
        ("https://customer.com", "https://shop.customer.com", False),  # subdomain
        ("https://customer.com", "https://evilcustomer.com", False),
        ("https://customer.com", "https://customer.com.evil.io", False),
        ("https://customer.com", "null", False),
        ("https://customer.com", None, False),
        ("https://customer.com", "", False),
    ],
)
async def test_origin_rules(site_url, origin, ok):
    show, reason, _ = await _decide(FakeDB(_site(url=site_url)), origin=origin)
    assert show is ok
    if not ok:
        assert reason == "origin"


# ── visitor `v` ────────────────────────────────────────────────────────────

async def test_v_over_length_hidden():
    assert (await _decide(FakeDB(_site()), vid="x" * 101))[1] == "bad_vid"


async def test_unknown_v_proceeds():
    show, _, _ = await _decide(FakeDB(_site(), visitors={}), vid="unknown-vid")
    assert show is True


@pytest.mark.parametrize("flags", [(True, False, False), (False, True, False), (False, False, True)])
async def test_blocked_visitor_hidden_and_zero_provider_calls(flags, _env):
    db = FakeDB(_site(), visitors={"vB": flags})
    show, reason, payload = await _decide(db, vid="vB")
    assert (show, reason, payload) == (False, "visitor_blocked", {"show": False})
    assert _env["n"] == 0  # no company lookup at all


async def test_cache_is_per_ip_only_visitor_b_still_hidden(_env):
    """Visitor A shown (company cached for the IP); do_not_resolve visitor B on
    the SAME IP must still get show:false — the decision is never cached."""
    redis = FakeRedis()
    visitors = {"vA": (False, False, False), "vB": (True, False, False)}
    a = await _decide(FakeDB(_site(), visitors=visitors), redis=redis, vid="vA")
    assert a[0] is True
    assert redis.sets == [f"greeting_company:{PUBLIC_IP}"]
    b = await _decide(FakeDB(_site(), visitors=visitors), redis=redis, vid="vB")
    assert b == (False, "visitor_blocked", {"show": False})
    # A third request for A hits the cache, not ip_org.
    c = await _decide(FakeDB(_site(), visitors=visitors), redis=redis, vid="vA")
    assert c[0] is True and _env["n"] == 1


# ── privacy ────────────────────────────────────────────────────────────────

async def test_privacy_relay_hidden():
    assert (await _decide(FakeDB(_site()), ip="2a09:bac3:1::1"))[1] == "privacy_relay"


@pytest.mark.parametrize("flag", ["vpn", "proxy", "tor", "hosting"])
async def test_cached_privacy_flags_hide(flag):
    redis = FakeRedis({f"ip_privacy:{PUBLIC_IP}": json.dumps({flag: True})})
    assert (await _decide(FakeDB(_site()), redis=redis))[1] == "vpn_proxy"


async def test_relay_alone_does_not_block():
    redis = FakeRedis({f"ip_privacy:{PUBLIC_IP}": json.dumps({"relay": True})})
    assert (await _decide(FakeDB(_site()), redis=redis))[0] is True


@pytest.mark.parametrize("raw", ["{not json", "[1,2]", "\"str\"", "null"])
async def test_malformed_privacy_is_a_miss(raw):
    redis = FakeRedis({f"ip_privacy:{PUBLIC_IP}": raw})
    assert (await _decide(FakeDB(_site()), redis=redis))[0] is True


# ── company / org_kind ─────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["eyeball", "datacenter", "cdn", None])
async def test_non_org_kind_hidden(kind, monkeypatch):
    async def _lookup(db, ip):
        return {"org_name": "Comcast", "domain": None, "asn": 7922, "org_kind": kind}

    monkeypatch.setattr(g, "lookup_ip_org", _lookup)
    assert (await _decide(FakeDB(_site())))[1] == "no_company"


async def test_domain_only_hidden(monkeypatch):
    async def _lookup(db, ip):
        return {"org_name": "", "domain": "globex.com", "asn": 1, "org_kind": "org"}

    monkeypatch.setattr(g, "lookup_ip_org", _lookup)
    assert (await _decide(FakeDB(_site())))[1] == "no_company"


async def test_no_ip_org_hit_hidden_and_negative_cached(monkeypatch):
    async def _lookup(db, ip):
        return None

    monkeypatch.setattr(g, "lookup_ip_org", _lookup)
    redis = FakeRedis()
    assert (await _decide(FakeDB(_site()), redis=redis))[1] == "no_company"
    assert json.loads(redis.data[f"greeting_company:{PUBLIC_IP}"]) == {"n": None, "k": None}


async def test_mock_mode_acme_only_after_gates(monkeypatch, _env):
    monkeypatch.setattr(settings, "mock_external_apis", True)
    ok = await _decide(FakeDB(_site()), ip=MOCK_IP)
    assert ok[0] is True and "Acme" in ok[2]["text"] and _env["n"] == 0
    # Gates still apply in mock mode.
    assert (await _decide(FakeDB(_site()), ip=MOCK_IP, origin="https://x.io"))[1] == "origin"
    db = FakeDB(_site(), visitors={"vB": (True, False, False)})
    assert (await _decide(db, ip=MOCK_IP, vid="vB"))[1] == "visitor_blocked"


# ── template rendering / sanitize ──────────────────────────────────────────

async def test_owner_template_and_cta():
    site = _site(greeting_templates={"default": {"text": "Hi {company}! See {company} pricing", "cta_url": "https://customer.com/demo"}})
    _, _, p = await _decide(FakeDB(site))
    assert p["text"] == "Hi Globex Corp! See Globex Corp pricing"
    assert p["cta_url"] == "https://customer.com/demo"


async def test_non_https_cta_dropped():
    site = _site(greeting_templates={"default": {"text": "Hi {company}", "cta_url": "javascript:alert(1)"}})
    _, _, p = await _decide(FakeDB(site))
    assert p["cta_url"] is None


async def test_company_name_sanitized_and_capped(monkeypatch):
    async def _lookup(db, ip):
        return {"org_name": "<script>x</script>{company}" + "A" * 300, "domain": None, "asn": 1, "org_kind": "org"}

    monkeypatch.setattr(g, "lookup_ip_org", _lookup)
    _, _, p = await _decide(FakeDB(_site()))
    assert "<" not in p["text"] and ">" not in p["text"] and "{" not in p["text"]
    assert len(p["text"]) <= 200


def test_schema_template_validation():
    from pydantic import ValidationError

    from apps.api.schemas.sites import GreetingTemplates, SiteUpdate

    ok = SiteUpdate(greeting_templates={"default": {"text": "Hi {company}", "cta_url": "https://a.com/x"}})
    assert ok.greeting_templates.default.text == "Hi {company}"
    for bad in (
        {"default": {"text": "Hi {name}"}},
        {"default": {"text": "x" * 201}},
        {"default": {"text": "<b>hi</b>"}},
        {"default": {"text": "hi", "cta_url": "http://a.com"}},
        {"default": {"text": "hi", "cta_url": "javascript:alert(1)"}},
        {"by_industry": {}},
    ):
        with pytest.raises(ValidationError):
            GreetingTemplates.model_validate(bad)


# ── G6: logs carry no PII ──────────────────────────────────────────────────

async def test_router_logs_only_site_show_reason(monkeypatch):
    """The router's greeting_decided event has exactly site_id/show/reason."""
    import apps.api.routers.greeting as router_mod

    captured: list[tuple[str, dict]] = []

    class _Log:
        def info(self, event, **kw):
            captured.append((event, kw))

        def warning(self, event, **kw):
            captured.append((event, kw))

    monkeypatch.setattr(router_mod, "logger", _Log())

    async def _decide_stub(db, redis, site_id, ip, origin, vid):
        return True, "shown", {"show": True, "template_id": "default", "text": "Welcome, Globex Corp team!", "cta_url": None}

    monkeypatch.setattr(router_mod.greeting_service, "decide_greeting", _decide_stub)
    monkeypatch.setattr(router_mod, "get_redis", lambda: None)
    req = SimpleNamespace(
        headers={"origin": "https://customer.com"},
        client=SimpleNamespace(host=PUBLIC_IP),
        scope={"type": "http"},
    )
    monkeypatch.setattr(router_mod, "resolve_client_ip", lambda r: PUBLIC_IP)
    resp = await router_mod.get_greeting.__wrapped__(req, site_id="site_acme", v="vid-123", db=None)
    assert resp.headers["cache-control"] == "no-store"
    assert captured == [("greeting_decided", {"site_id": "site_acme", "show": True, "reason": "shown"})]
    blob = json.dumps(captured)
    for pii in (PUBLIC_IP, "Globex", "globex.com", "vid-123", "customer.com"):
        assert pii not in blob


async def test_service_emits_no_logs_with_pii(caplog):
    caplog.set_level(logging.DEBUG)
    await _decide(FakeDB(_site()), vid="vid-123")
    for pii in (PUBLIC_IP, "Globex", "globex.com", "vid-123"):
        assert pii not in caplog.text
