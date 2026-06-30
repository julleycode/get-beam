"""P1 (own-data): durable _rta_svid server-cookie reconciliation.

When a returning visitor's CLIENT id is wiped (Safari ITP), the HttpOnly
_rta_svid cookie still carries the ORIGINAL visitor_id. The resolver's
prior-signal Check 0 recovers a prior identification from it for FREE, instead
of re-paying a provider to re-identify someone Beam already owns.
"""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.api.services.identity_resolver import IdentityResolver
from apps.api.services.identity_classification import identity_level, is_emailable_identity


def _make_visitor(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "site_id": "test-site",
        "visitor_id": f"v-new-{uuid.uuid4().hex[:8]}",
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


def _prior(email="cto@acme.com", full_name="Real Person"):
    return SimpleNamespace(
        email=email, full_name=full_name, city="Austin", region="TX", country="US",
    )


class TestSvidClassification:
    def test_svid_reconcile_is_person_level(self):
        assert identity_level("svid_reconcile") == "person"

    def test_svid_reconcile_is_emailable(self):
        assert is_emailable_identity("svid_reconcile") is True


class TestSvidReconcileCheck:
    @pytest.mark.asyncio
    async def test_matches_prior_identification_by_svid(self):
        resolver = _make_resolver()
        visitor = _make_visitor(server_visitor_id="v-orig-aaaa1111")
        resolver._identified_for_origin = AsyncMock(return_value=_prior())
        resolver._email_suppressed = AsyncMock(return_value=False)
        sentinel = object()
        resolver._save_identified = AsyncMock(return_value=sentinel)

        result = await resolver._check_prior_signals(visitor)

        assert result is sentinel
        args, _ = resolver._save_identified.call_args
        assert args[0] is visitor
        assert args[1]["email"] == "cto@acme.com"
        assert args[1]["confidence_score"] == 0.90
        assert args[2] == "svid_reconcile"

    @pytest.mark.asyncio
    async def test_skipped_when_no_svid(self):
        resolver = _make_resolver()
        visitor = _make_visitor(server_visitor_id=None, fingerprint=None)
        resolver.db.execute = AsyncMock(return_value=_result_returning(None))
        resolver._check_beam_identity_network = AsyncMock(return_value=None)
        resolver._identified_for_origin = AsyncMock()
        resolver._save_identified = AsyncMock()

        result = await resolver._check_prior_signals(visitor)

        assert result is None
        resolver._identified_for_origin.assert_not_called()
        resolver._save_identified.assert_not_called()

    @pytest.mark.asyncio
    async def test_skipped_when_svid_equals_self(self):
        resolver = _make_resolver()
        vid = "v-self-bbbb2222"
        visitor = _make_visitor(visitor_id=vid, server_visitor_id=vid, fingerprint=None)
        resolver.db.execute = AsyncMock(return_value=_result_returning(None))
        resolver._check_beam_identity_network = AsyncMock(return_value=None)
        resolver._identified_for_origin = AsyncMock()
        resolver._save_identified = AsyncMock()

        result = await resolver._check_prior_signals(visitor)

        assert result is None
        resolver._identified_for_origin.assert_not_called()
        resolver._save_identified.assert_not_called()

    @pytest.mark.asyncio
    async def test_skipped_when_origin_suppressed(self):
        # The original opted out (do_not_process) AFTER identification — never re-copy.
        resolver = _make_resolver()
        visitor = _make_visitor(server_visitor_id="v-orig-dddd4444", fingerprint=None)
        resolver._identified_for_origin = AsyncMock(return_value=_prior())
        resolver._email_suppressed = AsyncMock(return_value=True)
        resolver.db.execute = AsyncMock(return_value=_result_returning(None))
        resolver._check_beam_identity_network = AsyncMock(return_value=None)
        resolver._save_identified = AsyncMock()

        result = await resolver._check_prior_signals(visitor)

        assert result is None
        resolver._save_identified.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_save_when_prior_has_no_identity(self):
        resolver = _make_resolver()
        visitor = _make_visitor(server_visitor_id="v-orig-cccc3333", fingerprint=None)
        resolver._identified_for_origin = AsyncMock(
            return_value=SimpleNamespace(email=None, full_name=None, city=None, region=None, country=None)
        )
        resolver._email_suppressed = AsyncMock(return_value=False)
        resolver.db.execute = AsyncMock(return_value=_result_returning(None))
        resolver._check_beam_identity_network = AsyncMock(return_value=None)
        resolver._save_identified = AsyncMock()

        result = await resolver._check_prior_signals(visitor)

        assert result is None
        resolver._save_identified.assert_not_called()


class TestIdentifiedForOrigin:
    @pytest.mark.asyncio
    async def test_direct_hit_short_circuits(self):
        resolver = _make_resolver()
        prior = _prior()
        resolver.db.execute = AsyncMock(return_value=_result_returning(prior))
        out = await resolver._identified_for_origin("site", "v-orig")
        assert out is prior

    @pytest.mark.asyncio
    async def test_follows_one_canonical_merge_hop(self):
        # The root was itself merged (no own IdentifiedVisitor row): follow canonical.
        resolver = _make_resolver()
        prior = _prior()
        resolver.db.execute = AsyncMock(side_effect=[
            _result_returning(None),        # direct: no row for origin
            _result_returning("v-canon"),   # origin.canonical_visitor_id
            _result_returning(prior),       # IdentifiedVisitor for canon
        ])
        out = await resolver._identified_for_origin("site", "v-orig")
        assert out is prior

    @pytest.mark.asyncio
    async def test_none_when_no_row_and_no_canonical(self):
        resolver = _make_resolver()
        resolver.db.execute = AsyncMock(side_effect=[
            _result_returning(None),   # direct
            _result_returning(None),   # canonical
        ])
        out = await resolver._identified_for_origin("site", "v-orig")
        assert out is None
