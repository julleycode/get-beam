"""Identity P0 quality gates: privacy-relay IP, name/email consistency, emailability."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import apps.api.main  # noqa: F401 — register ORM mappers for IdentifiedVisitor
from apps.api.services.company_resolver import is_privacy_relay_ip, is_proxy_or_vpn
from apps.api.services.identity_classification import (
    PAID_PERSON_GRAPH_PROVIDERS,
    PERSON_LEVEL_PROVIDERS,
    identity_level,
    is_graph_candidate_provider,
    is_emailable_identity,
    name_email_consistent,
)
from apps.api.services.identity_resolver import IdentityResolver

pytestmark = pytest.mark.unit


class TestIsPrivacyRelayIp:
    def test_icloud_private_relay_prefix(self):
        assert is_privacy_relay_ip("2a09:bac3:627a:3050::4d0:11") is True
        assert is_privacy_relay_ip("2A09:BAC3:0000::1") is True

    def test_non_relay_ipv6(self):
        assert is_privacy_relay_ip("2001:db8::1") is False

    def test_residential_ipv4(self):
        assert is_privacy_relay_ip("203.0.113.10") is False

    def test_empty(self):
        assert is_privacy_relay_ip(None) is False
        assert is_privacy_relay_ip("") is False

    def test_ingest_still_keeps_relay(self):
        # Privacy-relay IPs must remain ingestable (real humans).
        assert is_proxy_or_vpn(
            {"vpn": False, "proxy": False, "tor": False, "relay": True, "hosting": False}
        ) is False


class TestNameEmailConsistent:
    def test_janet_danica_mismatch(self):
        assert name_email_consistent(
            "Janet Valla", "danica_naluz@sftoyota.com"
        ) is False

    def test_jsmith_matches(self):
        assert name_email_consistent("John Smith", "jsmith@acme.com") is True

    def test_dotted_local_matches(self):
        assert name_email_consistent("John Smith", "john.smith@acme.com") is True

    def test_missing_side_allows(self):
        assert name_email_consistent("Janet Valla", None) is True
        assert name_email_consistent(None, "danica_naluz@sftoyota.com") is True
        assert name_email_consistent("", "x@y.com") is True


class TestIdentityTierForProvider:
    """Canonical vocabulary (D1): the resolver writes identity_status directly as
    ``"candidate" if is_graph_candidate_provider(p) else "identified"``. main's
    main's per-provider status-mapping helper and its status constants are
    retired."""

    def test_paid_graph_is_candidate(self):
        assert is_graph_candidate_provider("rb2b") is True
        assert is_graph_candidate_provider("leadpipe") is True

    def test_owned_is_identified(self):
        assert is_graph_candidate_provider("form_capture") is False
        assert is_graph_candidate_provider("manual") is False
        assert is_graph_candidate_provider("svid_reconcile") is False


class TestEmailableProviders:
    @pytest.mark.parametrize("provider", sorted(PAID_PERSON_GRAPH_PROVIDERS))
    def test_paid_graphs_are_emailable_under_d2(self, provider):
        # D2 (locked): paid graphs are person-level and therefore emailable.
        # They stay on the candidate TIER (restrained to generic copy by the
        # personalization gate), which is a separate, orthogonal axis.
        assert identity_level(provider) == "person"
        assert is_graph_candidate_provider(provider) is True
        assert is_emailable_identity(provider) is True

    @pytest.mark.parametrize("provider", sorted(PERSON_LEVEL_PROVIDERS))
    def test_person_level_still_emailable(self, provider):
        assert is_emailable_identity(provider) is True

    def test_agent_and_abuse_still_block_owned(self):
        assert is_emailable_identity("form_capture", "agent-uuid") is False
        assert is_emailable_identity("form_capture", None, True) is False


class TestSaveAndResolveWiring:
    @pytest.mark.asyncio
    async def test_save_rejects_janet_danica_for_rb2b(self, monkeypatch):
        async def _ok_email(email):
            return True, None

        monkeypatch.setattr(
            "apps.api.services.email_validator.validate_email", _ok_email
        )
        db = MagicMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
        resolver = IdentityResolver(db, redis_client=None)
        visitor = SimpleNamespace(
            visitor_id="407a701d-ade4-4593-9078-5b665d48ba80",
            site_id="site_test",
            fingerprint=None,
            is_abuse_flagged=False,
        )
        row = await resolver._save_identified(
            visitor,
            {
                "full_name": "Janet Valla",
                "email": "danica_naluz@sftoyota.com",
                "confidence_score": 0.7,
            },
            "rb2b",
        )
        assert row is None
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_graph_save_reject_logs_success_false(self, monkeypatch):
        """Winner payload that fails _save_identified must not ledger success=True."""
        from apps.api.services import identity_resolver as ir_mod

        monkeypatch.setattr(ir_mod.settings, "leadpipe_api_key", "k")
        monkeypatch.setattr(ir_mod.settings, "leadpipe_enabled", True)
        monkeypatch.setattr(ir_mod.settings, "capturify_api_key", "")
        monkeypatch.setattr(ir_mod.settings, "capturify_enabled", False)
        monkeypatch.setattr(ir_mod.settings, "rb2b_api_key", "")
        monkeypatch.setattr(ir_mod.settings, "rb2b_enabled", False)
        resolver = IdentityResolver(MagicMock(), redis_client=None)
        resolver._call_leadpipe_api = AsyncMock(
            return_value={
                "full_name": "Janet Valla",
                "email": "danica_naluz@sftoyota.com",
            }
        )
        resolver._log_resolution = AsyncMock()
        resolver._save_identified = AsyncMock(return_value=None)
        visitor = SimpleNamespace(
            visitor_id="vid-1", site_id="site_test", ip_address="203.0.113.10"
        )
        result = await resolver._resolve_identity_graphs_parallel(visitor)
        assert result is None
        resolver._log_resolution.assert_awaited()
        args = resolver._log_resolution.await_args
        assert args.args[1] == "leadpipe"
        assert args.args[2] is False  # success
        assert args.args[3] == 0.0  # cost

    @pytest.mark.asyncio
    async def test_resolve_privacy_relay_sets_vpn_filtered(self, monkeypatch):
        monkeypatch.setattr(
            "apps.api.services.identity_resolver.settings.ipinfo_token", ""
        )
        db = MagicMock()
        db.commit = AsyncMock()
        resolver = IdentityResolver(db, redis_client=None)
        resolver._is_email_opted_out = AsyncMock(return_value=False)
        resolver._check_prior_signals = AsyncMock(return_value=None)
        resolver.was_recently_attempted = AsyncMock(return_value=False)
        resolver.check_daily_budget = AsyncMock(return_value=True)
        resolver._resolve_identity_graphs_parallel = AsyncMock(
            side_effect=AssertionError("paid graphs must not run for privacy relay")
        )

        visitor = SimpleNamespace(
            visitor_id="vid-relay",
            site_id="site_test",
            ip_address="2a09:bac3:627a:3050::4d0:11",
            do_not_resolve=False,
            fingerprint=None,
        )
        result = await resolver.resolve(visitor)
        assert result is None
        assert visitor.identity_status == "vpn_filtered"
        db.commit.assert_awaited()
        resolver._resolve_identity_graphs_parallel.assert_not_called()
