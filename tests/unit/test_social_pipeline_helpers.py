"""Unit tests for pipeline helpers: paid-response parsing + username derivation."""

import pytest

from apps.api.services.paid_osint import _parse_response
from apps.api.services.social_rules import (
    SITE_URL_TEMPLATES,
    derive_username_candidates,
)


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
    assert len(cands) <= 8
    for c in cands:
        assert 2 <= len(c["username"]) <= 30


def test_templates_have_placeholder():
    for tmpl in SITE_URL_TEMPLATES.values():
        assert "{u}" in tmpl
