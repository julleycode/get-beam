"""Unit tests for pipeline helpers: paid-response parsing + username derivation
+ the WhatsMyName-backed content check that replaced status-only validation."""

import pytest

from apps.api.services import social_rules as sr
from apps.api.services.paid_osint import _parse_response
from apps.api.services.social_rules import (
    SITE_URL_TEMPLATES,
    derive_username_candidates,
)


class _FakeResp:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


# ── OSINT Industries response parsing (defensive) ──

def test_parse_list_of_modules():
    payload = [
        {"module": "instagram", "status": "found",
         "data": {"username": "jdoe", "url": "https://instagram.com/jdoe", "profile_pic": "x"}},
        {"module": "telegram", "status": "found", "data": {"username": "jd"}},
        {"module": "ghost", "status": "not_found", "data": {}},
    ]
    accounts = _parse_response(payload)
    names = {a.site_name for a in accounts}
    assert "Instagram" in names and "Telegram" in names
    assert "Ghost" not in names  # not_found dropped
    ig = next(a for a in accounts if a.site_name == "Instagram")
    assert ig.kind == "profile" and ig.confidence == "confirmed"
    assert ig.source_engine == "osint-industries"
    assert ig.extra.get("username") == "jdoe"


def test_parse_wrapped_results_key():
    payload = {"results": [{"module": "x", "status": "found",
                            "data": {"url": "https://x.com/a", "username": "a"}}]}
    accounts = _parse_response(payload)
    assert len(accounts) == 1 and accounts[0].url == "https://x.com/a"


def test_parse_garbage_returns_empty():
    assert _parse_response(None) == []
    assert _parse_response({"nope": 1}) == []
    assert _parse_response("string") == []


# ── username candidate derivation ──

def test_candidates_known_handles_first():
    cands = derive_username_candidates(
        "john.doe@gmail.com", twitter_handle="@jdoe",
        github_url="https://github.com/johnd", full_name="John Doe",
    )
    usernames = [c["username"] for c in cands]
    assert usernames[0] == "jdoe"  # twitter handle is highest-signal
    assert cands[0]["known"] is True
    assert "johnd" in usernames  # github slug
    assert "john.doe" in usernames  # email local-part


def test_candidates_skip_generic_mailbox():
    cands = derive_username_candidates("info@acme.com")
    assert cands == []  # "info" is a generic mailbox, no name/handles


def test_candidates_capped_and_valid():
    cands = derive_username_candidates(
        "a.very.long.name.here@x.com", full_name="A Very Long Name Here",
    )
    assert len(cands) <= 12
    for c in cands:
        assert 2 <= len(c["username"]) <= 30


def test_templates_have_placeholder():
    for tmpl in SITE_URL_TEMPLATES.values():
        assert "{u}" in tmpl


# ── WhatsMyName data loading + filtering ──


def test_wmn_data_loads_and_filters():
    entries = sr._wmn_by_name()
    assert len(entries) > 500  # vendored file carries 708 sites
    assert all(e.get("e_string") for e in entries.values())  # nothing to verify without one
    assert all(e.get("uri_check") for e in entries.values())


def test_nsfw_category_substring_match():
    """Regression for the exact trap: WhatsMyName labels adult sites
    'xx NSFW xx', which an equality test against {"adult","nsfw","porn"} misses
    entirely — 39 sites' worth."""
    from apps.api.services.osint_scanner import is_skipped_category

    skip = {"adult", "nsfw", "porn"}
    assert is_skipped_category("xx NSFW xx", skip) is True
    assert is_skipped_category("Adult Content", skip) is True
    assert is_skipped_category("social", skip) is False
    # and the loader actually applies it
    assert not [
        n for n, e in sr._wmn_by_name().items()
        if "nsfw" in (e.get("cat") or "").lower()
    ]


def test_deep_tier_sites_all_resolve():
    """Every deep-tier display name must map to a real WhatsMyName entry and to
    a url template — a typo here silently drops a high-value site."""
    entries = sr._wmn_by_name()
    for display, wmn_name in sr.DEEP_TIER_WMN.items():
        assert wmn_name.lower() in entries, display
        assert display in SITE_URL_TEMPLATES, display


# ── content check (replaces status-code-only validation) ──


def test_content_check_accepts_expected_marker():
    entry = {"e_code": 200, "e_string": '"id":', "m_string": '"status": "404"'}
    assert sr._is_hit(entry, _FakeResp(200, '{"id": 42, "login": "jdoe"}')) is True


def test_content_check_rejects_soft_404():
    """200 with no expected marker — the failure mode status-only checking could
    not see (6 of 16 sites reported a ghost username as found)."""
    entry = {"e_code": 200, "e_string": '"id":', "m_string": None}
    assert sr._is_hit(entry, _FakeResp(200, "<html>Sign in to continue</html>")) is False


def test_content_check_rejects_on_m_string():
    entry = {"e_code": 200, "e_string": '"id":', "m_string": '"status": "404"'}
    body = '{"id": 0, "status": "404"}'
    assert sr._is_hit(entry, _FakeResp(200, body)) is False


def test_content_check_rejects_wrong_status():
    entry = {"e_code": 200, "e_string": '"id":', "m_string": None}
    assert sr._is_hit(entry, _FakeResp(404, '{"id": 42}')) is False


# ── two-tier request planning + budget ──


def _cands(n):
    return [{"username": f"user{i}", "known": False, "source": "name"} for i in range(n)]


def test_request_budget_capped(monkeypatch):
    monkeypatch.setattr(sr.settings, "osint_rules_max_requests", 40)
    assert len(sr._plan_checks(_cands(10))) == 40


def test_broad_tier_uses_single_candidate(monkeypatch):
    monkeypatch.setattr(sr.settings, "osint_rules_max_requests", 10_000)
    monkeypatch.setattr(sr.settings, "osint_rules_broad_candidates", 1)
    planned = sr._plan_checks(_cands(4))
    deep_names = set(sr.DEEP_TIER_WMN)
    broad = [p for p in planned if p[0] not in deep_names]
    assert broad, "broad tier produced no checks"
    assert {p[3]["username"] for p in broad} == {"user0"}  # candidates[0] only
    # deep tier still fans out across every candidate
    deep = [p for p in planned if p[0] in deep_names]
    assert len({p[3]["username"] for p in deep}) == 4


def test_deep_tier_url_is_human_facing_not_the_api_probe():
    """The stored url must be clickable by a salesperson; WhatsMyName's
    uri_check for these sites is an API endpoint whose e_string only matches
    that API's response, so the two urls are deliberately different."""
    planned = sr._plan_checks(_cands(1))
    gh = [p for p in planned if p[0] == "GitHub"]
    assert gh and gh[0][1] == "https://github.com/user0"
    assert "api.github.com" in gh[0][2]["uri_check"]


def test_broad_tier_only_eligible_categories(monkeypatch):
    monkeypatch.setattr(sr.settings, "osint_rules_max_requests", 10_000)
    monkeypatch.setattr(sr.settings, "osint_rules_categories", "finance")
    planned = sr._plan_checks(_cands(1))
    broad = [p for p in planned if p[0] not in set(sr.DEEP_TIER_WMN)]
    assert broad and all((p[2].get("cat") or "").lower() == "finance" for p in broad)
