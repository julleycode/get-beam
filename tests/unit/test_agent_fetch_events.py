"""Unit tests for Handoff Detection H1 — per-hit fetch events + tiering.

Covers:
- classify_tier: on-demand vs index for all 10 documented tokens (AC-H1-2)
- tier-map completeness tripwire over every _VENDOR_TOKENS token (AC-H1-2)
- persist_agent_fetch_event: one insert per hit, correct columns (AC-H1-1)
- persist_agent_fetch_event: fail-open isolation, no PII in log (AC-H1-3)
- retention config default present

All DB interaction is mocked (AsyncSession) — no live DB. The Hybrid
retention-purge behavior test lives in tests/integration/test_retention_purge.py
(E7, Docker-gated).
"""

from unittest.mock import AsyncMock, Mock

import pytest

from apps.api.services.agent_classifier import (
    AgentClassification,
    _ON_DEMAND_TOKENS,
    _VENDOR_TOKENS,
    classify_tier,
)
from apps.api.services import agent_visit_persistence
from apps.api.services.agent_visit_persistence import persist_agent_fetch_event

# Locked tier map (mirror of the plan's LOCKED Decisions table). The
# completeness test asserts this is exactly the union of _VENDOR_TOKENS.
_EXPECTED_ON_DEMAND = {
    "chatgpt-user", "oai-searchbot", "claude-user", "claude-searchbot", "perplexity-user",
}
_EXPECTED_INDEX = {
    "gptbot", "claudebot", "anthropic-ai", "perplexitybot", "bytespider",
}


class TestTierClassification:
    @pytest.mark.parametrize("token", sorted(_EXPECTED_ON_DEMAND))
    @pytest.mark.unit
    def test_on_demand_tokens(self, token):
        assert classify_tier(token) == "on-demand"

    @pytest.mark.parametrize("token", sorted(_EXPECTED_INDEX))
    @pytest.mark.unit
    def test_index_tokens(self, token):
        assert classify_tier(token) == "index"


class TestTierMapCompleteness:
    @pytest.mark.unit
    def test_tier_map_covers_all_vendor_tokens(self):
        """Every token in _VENDOR_TOKENS must classify without raising, and the
        on-demand/index split must match the locked tier map exactly. This is the
        tripwire that fails loudly if a future token is added without a tier.
        """
        all_tokens = {t for tokens in _VENDOR_TOKENS.values() for t in tokens}

        # Locked map covers exactly the known vendor tokens — no more, no less.
        assert _EXPECTED_ON_DEMAND | _EXPECTED_INDEX == all_tokens
        # The on-demand set the classifier actually uses matches the locked map.
        assert set(_ON_DEMAND_TOKENS) == _EXPECTED_ON_DEMAND

        for token in all_tokens:
            tier = classify_tier(token)
            assert tier in ("on-demand", "index")
            expected = "on-demand" if token in _EXPECTED_ON_DEMAND else "index"
            assert tier == expected, f"{token} misclassified as {tier}"


def _mock_session():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


class TestRowCreatedPerHit:
    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_row_created_per_hit(self):
        db = _mock_session()
        classification = AgentClassification(
            vendor="openai",
            product_or_ua_token="chatgpt-user",
            verification_method="ua-only",
        )

        await persist_agent_fetch_event(
            db, "site_abc", classification, "on-demand", "1.2.3.4", "/pricing"
        )

        # Exactly one insert + one commit; no rollback on the happy path.
        db.execute.assert_awaited_once()
        db.commit.assert_awaited_once()
        db.rollback.assert_not_awaited()

        # Inspect the compiled insert values.
        stmt = db.execute.await_args.args[0]
        params = stmt.compile().params
        assert params["site_id"] == "site_abc"
        assert params["vendor"] == "openai"
        assert params["raw_ua_token"] == "chatgpt-user"
        assert params["tier"] == "on-demand"
        assert params["page_path"] == "/pricing"
        assert params["ip_address"] == "1.2.3.4"
        assert params["verification_method"] == "ua-only"

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_empty_ip_coerced_to_none(self):
        db = _mock_session()
        classification = AgentClassification("openai", "gptbot", "ua-only")

        await persist_agent_fetch_event(
            db, "site_abc", classification, "index", "", None
        )

        stmt = db.execute.await_args.args[0]
        params = stmt.compile().params
        assert params["ip_address"] is None
        assert params["page_path"] is None
        assert params["tier"] == "index"


class TestWriteFailureIsolated:
    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_write_failure_isolated(self, monkeypatch):
        db = _mock_session()
        db.execute = AsyncMock(side_effect=RuntimeError("boom: secret-ua Mozilla/5.0"))
        warn = Mock()
        monkeypatch.setattr(agent_visit_persistence.logger, "warning", warn)

        classification = AgentClassification(
            vendor="anthropic",
            product_or_ua_token="claude-user",
            verification_method="ua-only",
        )

        # No exception propagates.
        result = await persist_agent_fetch_event(
            db, "site_abc", classification, "on-demand", "9.9.9.9", "/secret-path"
        )
        assert result is None
        db.rollback.assert_awaited_once()

        # Log carries keys-only — no raw UA, no IP, no page_path (PII/GDPR guard).
        warn.assert_called_once()
        _args, kwargs = warn.call_args
        assert set(kwargs.keys()) == {"site_id", "vendor", "error"}
        assert kwargs["site_id"] == "site_abc"
        assert kwargs["vendor"] == "anthropic"
        assert "9.9.9.9" not in str(kwargs)
        assert "/secret-path" not in str(kwargs)


class TestRetentionConfig:
    @pytest.mark.unit
    def test_retention_config_present(self):
        from apps.api.config import settings

        assert settings.agent_fetch_event_retention_days == 90
