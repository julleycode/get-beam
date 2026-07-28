"""Unit tests for the published per-agent IP-range refresh (offline, no network).

The parser is what stands between a vendor changing its document shape and the
verification layer silently deciding every real agent is a forgery, so the
fail-open paths matter as much as the happy one.
"""

import pytest

from apps.api.services.agent_ip_range_refresh import (
    PUBLISHED_RANGE_SOURCES,
    normalize_prefixes,
)

pytestmark = pytest.mark.unit


def test_parses_the_published_prefixes_shape():
    """Observed shape of https://openai.com/gptbot.json."""
    payload = {
        "creationTime": "2026-07-01T00:00:00Z",
        "prefixes": [
            {"ipv4Prefix": "132.196.86.0/24"},
            {"ipv4Prefix": "172.182.202.0/25"},
            {"ipv6Prefix": "2600:1f00::/40"},
        ],
    }
    assert normalize_prefixes(payload) == [
        "132.196.86.0/24",
        "172.182.202.0/25",
        "2600:1f00::/40",
    ]


def test_round_trips_the_stored_shape():
    """What we write must parse back, so a stored file can be re-read by the
    same code path that consumed the upstream document."""
    assert normalize_prefixes({"ranges": ["10.0.0.0/8"]}) == ["10.0.0.0/8"]


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "nope",
        {},
        {"prefixes": "not-a-list"},
        {"prefixes": [{"unexpectedKey": "10.0.0.0/8"}, "junk", None]},
    ],
)
def test_unknown_shapes_yield_nothing_rather_than_raising(payload):
    """Empty means "learned nothing", and the caller keeps the dataset it already
    had. Raising here would abort the refresh for every remaining agent."""
    assert normalize_prefixes(payload) == []


def test_sources_are_keyed_by_agent_token_never_by_vendor():
    """A per-vendor key would merge OpenAI's three documents and destroy the
    ability to spot one agent arriving on another's range."""
    assert "gptbot" in PUBLISHED_RANGE_SOURCES
    assert "oai-searchbot" in PUBLISHED_RANGE_SOURCES
    assert "chatgpt-user" in PUBLISHED_RANGE_SOURCES
    assert "openai" not in PUBLISHED_RANGE_SOURCES
    # Anthropic publishes no ranges, so it must have no source at all.
    assert not any(k.startswith("claude") or k == "anthropic-ai" for k in PUBLISHED_RANGE_SOURCES)
