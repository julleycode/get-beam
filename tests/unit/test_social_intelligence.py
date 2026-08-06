"""Unit tests for SocialIntelligence.store_social_context (merge semantics + no meter stamp).

Covers AC-1..AC-6 and AC-10 of
process/features/visitors-identity/active/social-context-merge_07-08-26/.

No DB: the session is an AsyncMock and the profile is a SimpleNamespace
(precedent: tests/unit/test_content_enrich.py:10,97).
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from apps.api.services.social_intelligence import SocialIntelligence

pytestmark = pytest.mark.unit


def _svc():
    db = AsyncMock()
    return SocialIntelligence(db), db


def _profile(social_context=None, updated_at=None):
    return SimpleNamespace(
        visitor_id="vis_1",
        social_context=social_context,
        social_context_updated_at=updated_at,
    )


@pytest.mark.asyncio
async def test_store_merges_preserving_sibling_keys():
    """AC-1 sibling keys survive + AC-10 the JSONB attribute is REASSIGNED."""
    svc, db = _svc()
    profile = _profile({"deep_research": {"summary": "keep me"}, "osint_scan": {"accounts": []}})
    original = profile.social_context

    await svc.store_social_context(profile, {"recent_posts": [], "topics": ["AI/ML"]})

    assert profile.social_context["deep_research"] == {"summary": "keep me"}
    assert profile.social_context["osint_scan"] == {"accounts": []}
    assert profile.social_context["topics"] == ["AI/ML"]
    # AC-10 / G8: a new dict object, not an in-place mutation.
    assert profile.social_context is not original
    assert original == {"deep_research": {"summary": "keep me"}, "osint_scan": {"accounts": []}}
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_store_writes_new_keys():
    """AC-2."""
    svc, _ = _svc()
    profile = _profile({"deep_research": {"summary": "x"}})

    await svc.store_social_context(
        profile, {"recent_posts": [{"content": "hi"}], "topics": ["SaaS"], "sentiment": None}
    )

    assert profile.social_context["recent_posts"] == [{"content": "hi"}]
    assert profile.social_context["topics"] == ["SaaS"]
    assert profile.social_context["sentiment"] is None


@pytest.mark.asyncio
async def test_store_incoming_key_wins():
    """AC-3 / G7: last write wins per key."""
    svc, _ = _svc()
    profile = _profile({"topics": ["OLD"], "deep_research": {"summary": "keep"}})

    await svc.store_social_context(profile, {"topics": ["NEW"]})

    assert profile.social_context["topics"] == ["NEW"]
    assert profile.social_context["deep_research"] == {"summary": "keep"}


@pytest.mark.asyncio
async def test_store_handles_none_start_state():
    """AC-4 / G2: None start state merges without raising and yields exactly `context`."""
    svc, _ = _svc()
    profile = _profile(None)
    context = {"recent_posts": [], "topics": [], "sentiment": None}

    await svc.store_social_context(profile, context)

    assert profile.social_context == context


@pytest.mark.asyncio
async def test_resolution_sweep_same_iteration_preserves_enrich_keys():
    """AC-5: the reported bug — real disjoint key sets from the Celery sweep.

    Prior state = the enrich_tier1 / _fetch_and_store_content keys; incoming =
    the fetch_social_context keys. Disjoint, so the old overwrite was pure loss.
    """
    svc, _ = _svc()
    prior = {
        "youtube": {"videos": ["v1"]},
        "reddit": {"posts": ["r1"]},
        "company_content": {"pages": ["about"]},
    }
    profile = _profile(dict(prior))

    await svc.store_social_context(
        profile,
        {"recent_posts": [{"content": "tweet"}], "topics": ["Engineering"], "sentiment": None},
    )

    for key, value in prior.items():
        assert profile.social_context[key] == value, f"{key} was destroyed"
    assert profile.social_context["topics"] == ["Engineering"]


@pytest.mark.asyncio
async def test_store_does_not_touch_updated_at():
    """AC-6 / BUG-2: the deep-research meter column is never stamped here."""
    svc, _ = _svc()
    preset = datetime(2020, 1, 1, tzinfo=timezone.utc)
    profile = _profile({"a": 1}, updated_at=preset)

    await svc.store_social_context(profile, {"topics": []})
    assert profile.social_context_updated_at == preset

    profile_none = _profile({"a": 1}, updated_at=None)
    await svc.store_social_context(profile_none, {"topics": []})
    assert profile_none.social_context_updated_at is None
