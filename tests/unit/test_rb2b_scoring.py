"""RB2B provider: score parsing/normalization + candidate-tier landing.

Identity-honesty Phase 1 (A3). `_call_rb2b_api`'s score handling had ZERO test
coverage before this file, despite being the number the dashboard shows as
"confidence" and the number the old design would have used to decide whether a
match was trustworthy. These tests pin the parsing contract AND the rule that
matters most: no score, however high, promotes an RB2B match past "candidate".
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ORM classes are constructed below; importing main first registers the SQLAlchemy
# mappers (and the PII hooks) so IdentifiedVisitor(...) doesn't raise.
import apps.api.main  # noqa: F401
from apps.api.services.identity_classification import GRAPH_CANDIDATE_PROVIDERS
from apps.api.services.identity_resolver import IdentityResolver

pytestmark = pytest.mark.unit


def _make_visitor(**overrides):
    defaults = {
        "site_id": "test-site",
        "visitor_id": f"v-{uuid.uuid4().hex[:8]}",
        "ip_address": "203.0.113.42",
        "user_agent": "Mozilla/5.0",
        "fingerprint": None,
        "identity_status": "anonymous",
        "is_abuse_flagged": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_resolver():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    return IdentityResolver(db=db, redis_client=MagicMock())


def _mock_rb2b(client_cls: MagicMock, hem_results: list, profile: dict) -> MagicMock:
    """Wire the two-step RB2B chain onto a mocked httpx.AsyncClient class."""
    hem_resp = MagicMock(status_code=200)
    hem_resp.json.return_value = {"results": hem_results}
    profile_resp = MagicMock(status_code=200)
    profile_resp.json.return_value = profile

    client = AsyncMock()
    client.post = AsyncMock(side_effect=[hem_resp, profile_resp])
    client_cls.return_value.__aenter__ = AsyncMock(return_value=client)
    client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return client


async def _call_rb2b(hem_results: list, profile: dict) -> dict | None:
    resolver = _make_resolver()
    with patch(
        "apps.api.services.identity_providers.rb2b.settings"
    ) as mock_settings, patch(
        "apps.api.services.identity_providers.rb2b.httpx.AsyncClient"
    ) as client_cls:
        mock_settings.rb2b_api_key = "test-key"
        _mock_rb2b(client_cls, hem_results, profile)
        return await resolver._call_rb2b_api(_make_visitor())


_PROFILE = {"result": {"work_email": "person@example.com", "full_name": "A Person"}}


class TestRb2bScoreParsing:
    @pytest.mark.asyncio
    async def test_normalizes_0_100_scale_to_0_1(self):
        result = await _call_rb2b([{"md5": "h", "score": 87}], _PROFILE)
        assert result is not None
        assert result["confidence_score"] == pytest.approx(0.87)

    @pytest.mark.asyncio
    async def test_leaves_already_normalized_score_alone(self):
        result = await _call_rb2b([{"md5": "h", "score": 0.42}], _PROFILE)
        assert result["confidence_score"] == pytest.approx(0.42)

    @pytest.mark.asyncio
    async def test_ceiling_is_0_99(self):
        # A perfect 100 must not read as absolute certainty — it is still a guess.
        result = await _call_rb2b([{"md5": "h", "score": 100}], _PROFILE)
        assert result["confidence_score"] == 0.99

    @pytest.mark.asyncio
    async def test_ceiling_applies_to_already_normalized_over_one(self):
        result = await _call_rb2b([{"md5": "h", "score": 1.0}], _PROFILE)
        assert result["confidence_score"] == 0.99

    @pytest.mark.asyncio
    async def test_floor_is_zero(self):
        result = await _call_rb2b([{"md5": "h", "score": -5}], _PROFILE)
        assert result["confidence_score"] == 0.0

    @pytest.mark.asyncio
    async def test_picks_highest_scoring_result(self):
        result = await _call_rb2b(
            [
                {"md5": "low", "score": 10},
                {"md5": "best", "score": 95},
                {"md5": "mid", "score": 50},
            ],
            _PROFILE,
        )
        assert result["confidence_score"] == pytest.approx(0.95)

    @pytest.mark.asyncio
    async def test_returns_none_when_no_hem_results(self):
        assert await _call_rb2b([], _PROFILE) is None

    @pytest.mark.asyncio
    async def test_returns_none_when_result_has_no_hash(self):
        assert await _call_rb2b([{"score": 90}], _PROFILE) is None

    @pytest.mark.asyncio
    async def test_returns_none_when_profile_has_no_email(self):
        assert await _call_rb2b([{"md5": "h", "score": 90}], {"result": {}}) is None

    @pytest.mark.asyncio
    async def test_prefers_work_email_over_personal(self):
        result = await _call_rb2b(
            [{"md5": "h", "score": 90}],
            {
                "result": {
                    "work_email": "work@example.com",
                    "personal_emails": ["home@example.com"],
                }
            },
        )
        assert result["email"] == "work@example.com"


class TestRb2bLandsOnCandidateTier:
    """AC1: the score never promotes — 0.99 is still only a candidate."""

    def test_rb2b_is_a_graph_candidate_provider(self):
        assert "rb2b" in GRAPH_CANDIDATE_PROVIDERS

    @pytest.mark.asyncio
    async def test_max_score_rb2b_match_still_lands_on_candidate(self):
        from apps.api.services.identity_resolver import IdentityResolver as _IR

        resolver = _make_resolver()
        visitor = _make_visitor()
        resolver._log_owned_resolution = AsyncMock()
        resolver._upsert_beam_identity = AsyncMock()

        # full_name only (no email) → skips the email-dedup lookup entirely, so
        # the mocked db.execute can't accidentally fake a "merge" result.
        await _IR._save_identified(
            resolver,
            visitor,
            {"full_name": "A Person", "confidence_score": 0.99},
            "rb2b",
        )

        assert visitor.identity_status == "candidate"
