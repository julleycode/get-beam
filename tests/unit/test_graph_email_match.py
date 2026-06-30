"""P6 (own-data): cross-customer graph match by hashed email (email_bidx).

The graph writes email_bidx on every upsert but never read it — matching only on
exact fingerprint. P6 reads it: a freshly-captured email inherits the name an
earlier identification on ANY Beam site already has, deterministically and free
(the owned replacement for the paid PDL enrich P3 turned off).
"""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.services.identity_resolver import IdentityResolver


def _make_visitor(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "site_id": "test-site",
        "visitor_id": f"v-{uuid.uuid4().hex[:8]}",
        "ip_address": "203.0.113.42",
        "fingerprint": None,
        "server_visitor_id": None,
        "identity_status": "anonymous",
        "do_not_resolve": False,
        "first_seen": datetime.now(timezone.utc),
        "last_seen": datetime.now(timezone.utc),
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


def _result_returning(obj):
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=obj)
    return r


class TestGraphNodeByEmail:
    @pytest.mark.asyncio
    async def test_returns_node_for_matching_email(self):
        resolver = _make_resolver()
        node = SimpleNamespace(full_name="Graph Person", confidence_score=0.9)
        resolver.db.execute = AsyncMock(return_value=_result_returning(node))
        out = await resolver._graph_node_by_email("person@acme.com")
        assert out is node

    @pytest.mark.asyncio
    async def test_none_for_empty_email(self):
        resolver = _make_resolver()
        assert await resolver._graph_node_by_email("") is None


class TestCapturedEmailGraphEnrichment:
    async def _run_check1(self, graph_node):
        resolver = _make_resolver()
        visitor = _make_visitor()
        # Check 1's VisitorEmail lookup returns a captured email.
        resolver.db.execute = AsyncMock(return_value=_result_returning("owner@acme.com"))
        resolver._graph_node_by_email = AsyncMock(return_value=graph_node)
        resolver._save_identified = AsyncMock(return_value="SAVED")
        with patch("apps.api.services.identity_resolver.settings") as s:
            s.enrich_captured_email_pdl = False
            result = await resolver._check_prior_signals(visitor)
        return resolver, result

    @pytest.mark.asyncio
    async def test_inherits_name_from_graph(self):
        node = SimpleNamespace(full_name="Cross Site", confidence_score=0.9)
        resolver, result = await self._run_check1(node)
        assert result == "SAVED"
        data = resolver._save_identified.call_args[0][1]
        provider = resolver._save_identified.call_args[0][2]
        assert provider == "form_capture"
        assert data["email"] == "owner@acme.com"
        assert data["full_name"] == "Cross Site"
        assert data["confidence_score"] == 0.85  # corroborated by the graph

    @pytest.mark.asyncio
    async def test_basic_save_when_no_graph_match(self):
        resolver, result = await self._run_check1(None)
        assert result == "SAVED"
        data = resolver._save_identified.call_args[0][1]
        assert data["full_name"] is None
        assert data["confidence_score"] == 0.80
