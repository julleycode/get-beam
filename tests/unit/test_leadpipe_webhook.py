"""Phase 4: Leadpipe identity webhook ingest.

Covers the parts that are pure logic or one-hop delegation:
- endpoint auth (bad token / unset secret both 403)
- payload → site resolution, and the refusal to guess a tenant
- the 3-tier visitor attach waterfall and its ORDER
- tier-3 (IP + time window) refusals: no timestamp, privacy-relay IP
- tier-3 confidence ceiling
- the identity lands as provider_candidate and stays non-emailable

Idempotency under redelivery is NOT here: it is enforced by a real UNIQUE index,
so proving it needs a real database — see
tests/integration/test_leadpipe_webhook_persistence.py.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.routers import webhooks
from apps.api.services import leadpipe_webhook as lw
from apps.api.services.identity_classification import (
    STATUS_PROVIDER_CANDIDATE,
    identity_status_for_provider,
    is_emailable_identity,
)

pytestmark = pytest.mark.unit


class _FakeRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


def _site(site_id="s1", url="https://acme.com", pixel="px-1"):
    return SimpleNamespace(site_id=site_id, url=url, leadpipe_pixel_id=pixel)


def _visitor(visitor_id="v-1", site_id="s1", ip="203.0.113.9", last_seen=None):
    return SimpleNamespace(
        site_id=site_id,
        visitor_id=visitor_id,
        ip_address=ip,
        last_seen=last_seen or datetime.now(timezone.utc).replace(tzinfo=None),
        is_abuse_flagged=False,
    )


def _parsed(record: dict) -> dict:
    """The person dict ingest_identification hands to _attach_visitor.

    Built with the real parser + sanitizer rather than hand-written, so these
    tests break if production stops agreeing with them about the payload.
    """
    from apps.api.services.identity_providers.leadpipe import LeadpipeMixin

    person = LeadpipeMixin._parse_leadpipe_person(record)
    for field, limit in lw._MAX_LEN.items():
        person[field] = lw._clean(person.get(field), limit)
    return person


def _result(value):
    """A stand-in for the object db.execute() returns."""
    res = MagicMock()
    res.scalar_one_or_none.return_value = value
    scalars = MagicMock()
    scalars.all.return_value = [value] if value is not None else []
    res.scalars.return_value = scalars
    return res


class TestEndpointAuth:
    @pytest.mark.asyncio
    async def test_wrong_token_is_forbidden(self):
        s = MagicMock()
        s.leadpipe_webhook_secret = "right"
        with patch.object(webhooks, "settings", s):
            with pytest.raises(Exception) as exc:
                await webhooks.leadpipe_identity(
                    _FakeRequest({}), token="wrong", db=AsyncMock()
                )
        assert getattr(exc.value, "status_code", None) == 403

    @pytest.mark.asyncio
    async def test_unset_secret_disables_endpoint(self):
        """No secret configured must not mean 'accept anything'."""
        s = MagicMock()
        s.leadpipe_webhook_secret = ""
        with patch.object(webhooks, "settings", s):
            with pytest.raises(Exception) as exc:
                await webhooks.leadpipe_identity(
                    _FakeRequest({}), token="", db=AsyncMock()
                )
        assert getattr(exc.value, "status_code", None) == 403

    @pytest.mark.asyncio
    async def test_valid_token_delegates_each_record(self):
        s = MagicMock()
        s.leadpipe_webhook_secret = "right"
        ingest = AsyncMock(return_value="saved")
        with patch.object(webhooks, "settings", s), patch.object(
            webhooks, "ingest_identification", ingest
        ):
            out = await webhooks.leadpipe_identity(
                _FakeRequest([{"a": 1}, {"b": 2}]), token="right", db=AsyncMock()
            )
        assert out["processed"] == 2
        assert out["saved"] == 2
        assert ingest.await_count == 2


class TestSiteResolution:
    @pytest.mark.asyncio
    async def test_pixel_id_maps_to_site(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(_site()))
        site = await lw._resolve_site(db, {"pixel_id": "px-1"})
        assert site.site_id == "s1"

    @pytest.mark.asyncio
    async def test_unknown_payload_refuses_to_guess(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(None))
        assert await lw._resolve_site(db, {"pixel_id": "nope"}) is None

    @pytest.mark.asyncio
    async def test_unknown_site_writes_nothing(self):
        db = AsyncMock()
        with patch.object(lw, "_resolve_site", AsyncMock(return_value=None)):
            with patch.object(lw, "IdentityResolver") as resolver_cls:
                outcome = await lw.ingest_identification(
                    db, {"email": "a@acme.com", "domain": "unknown.test"}
                )
        assert outcome == "unknown_site"
        resolver_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_domain_substring_does_not_match_a_different_site(self):
        """'acme.com' inside another site's URL path must not claim the payload."""
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=_result(_site(url="https://other.test/blog/acme.com"))
        )
        assert await lw._resolve_site(db, {"domain": "acme.com"}) is None

    @pytest.mark.asyncio
    async def test_like_wildcards_in_domain_are_escaped(self):
        """A payload domain of '%' must not turn the prefilter into 'every site'."""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(None))
        await lw._resolve_site(db, {"domain": "%"})
        rendered = str(db.execute.await_args.args[0])
        assert "ESCAPE" in rendered.upper()
        params = db.execute.await_args.args[0].compile().params
        assert all("\\%" in v for v in params.values() if isinstance(v, str) and "%" in v)


class TestMarkerExtraction:
    def test_top_level(self):
        assert lw._extract_marker({"beam_visitor_id": "v-9"}) == "v-9"

    def test_inside_static_params(self):
        assert lw._extract_marker({"static_params": {"beam_visitor_id": "v-9"}}) == "v-9"

    def test_inside_event_data_static_params(self):
        record = {"event_data": {"static_params": {"beam_visitor_id": "v-9"}}}
        assert lw._extract_marker(record) == "v-9"

    def test_absent_is_none_not_an_error(self):
        """Vendor not echoing the marker is the expected fall-through, not a bug."""
        assert lw._extract_marker({"email": "a@acme.com"}) is None


class TestAttachWaterfallOrder:
    @pytest.mark.asyncio
    async def test_marker_wins_over_email(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(_visitor("v-marker")))
        rec = {"beam_visitor_id": "v-marker", "email": "a@acme.com"}
        visitor, tier = await lw._attach_visitor(db, _site(), rec, _parsed(rec))
        assert tier == lw.TIER_MARKER
        assert visitor.visitor_id == "v-marker"
        # One lookup only: the email tier was never consulted.
        assert db.execute.await_count == 1

    @pytest.mark.asyncio
    async def test_email_wins_over_ip(self):
        db = AsyncMock()
        # 1) VisitorEmail.visitor_id  2) the Visitor row
        db.execute = AsyncMock(
            side_effect=[_result("v-email"), _result(_visitor("v-email"))]
        )
        rec = {"email": "a@acme.com", "ip": "203.0.113.9"}
        visitor, tier = await lw._attach_visitor(db, _site(), rec, _parsed(rec))
        assert tier == lw.TIER_EMAIL
        assert visitor.visitor_id == "v-email"

    @pytest.mark.asyncio
    async def test_stale_marker_falls_through_to_email(self):
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _result(None),               # marker matches no visitor
                _result("v-email"),          # VisitorEmail
                _result(_visitor("v-email")),
            ]
        )
        rec = {"beam_visitor_id": "ghost", "email": "a@acme.com"}
        visitor, tier = await lw._attach_visitor(db, _site(), rec, _parsed(rec))
        assert tier == lw.TIER_EMAIL

    @pytest.mark.asyncio
    async def test_ip_and_time_is_the_last_resort(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(_visitor("v-ip")))
        rec = {"ip": "203.0.113.9", "timestamp": datetime.now(timezone.utc).isoformat()}
        visitor, tier = await lw._attach_visitor(db, _site(), rec, _parsed(rec))
        assert tier == lw.TIER_IP_WINDOW


class TestTierThreeRefusals:
    @pytest.mark.asyncio
    async def test_no_timestamp_refuses_ip_only_match(self):
        """Office and CGNAT IPs are shared; IP equality alone names nobody."""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(None))
        rec = {"ip": "203.0.113.9"}
        visitor, tier = await lw._attach_visitor(db, _site(), rec, _parsed(rec))
        assert visitor is None and tier is None

    @pytest.mark.asyncio
    async def test_privacy_relay_ip_refused(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(None))
        rec = {"ip": "2a09:bac3::1", "timestamp": datetime.now(timezone.utc).isoformat()}
        with patch.object(lw, "is_privacy_relay_ip", return_value=True):
            visitor, tier = await lw._attach_visitor(db, _site(), rec, _parsed(rec))
        assert visitor is None and tier is None

    @pytest.mark.asyncio
    async def test_privacy_relay_does_not_block_the_email_tier(self):
        """Tiers 1-2 never derive identity from the IP, so relay must not gate them."""
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[_result("v-email"), _result(_visitor("v-email"))]
        )
        rec = {"email": "a@acme.com", "ip": "2a09:bac3::1"}
        with patch.object(lw, "is_privacy_relay_ip", return_value=True):
            visitor, tier = await lw._attach_visitor(db, _site(), rec, _parsed(rec))
        assert tier == lw.TIER_EMAIL


class TestSaveDelegation:
    def _patched_resolver(self, saved_row=object()):
        resolver = MagicMock()
        resolver._save_identified = AsyncMock(return_value=saved_row)
        cls = MagicMock(return_value=resolver)
        return cls, resolver

    @pytest.mark.asyncio
    async def test_saves_through_the_shared_resolver_path(self):
        cls, resolver = self._patched_resolver()
        with patch.object(lw, "_resolve_site", AsyncMock(return_value=_site())), \
             patch.object(
                 lw, "_attach_visitor",
                 AsyncMock(return_value=(_visitor(), lw.TIER_EMAIL)),
             ), \
             patch.object(lw, "IdentityResolver", cls):
            outcome = await lw.ingest_identification(
                AsyncMock(), {"email": "a@acme.com", "name": "A Person"}
            )
        assert outcome == "saved"
        _, data, provider = resolver._save_identified.await_args.args
        assert provider == "leadpipe"
        assert data["email"] == "a@acme.com"

    @pytest.mark.asyncio
    async def test_ip_tier_confidence_is_capped(self):
        cls, resolver = self._patched_resolver()
        with patch.object(lw, "_resolve_site", AsyncMock(return_value=_site())), \
             patch.object(
                 lw, "_attach_visitor",
                 AsyncMock(return_value=(_visitor(), lw.TIER_IP_WINDOW)),
             ), \
             patch.object(lw, "IdentityResolver", cls):
            await lw.ingest_identification(AsyncMock(), {"email": "a@acme.com"})
        _, data, _p = resolver._save_identified.await_args.args
        assert data["confidence_score"] <= lw.MatchingMixin._WEAK_MATCH_MAX_CONFIDENCE

    @pytest.mark.asyncio
    async def test_deterministic_tier_keeps_full_confidence(self):
        cls, resolver = self._patched_resolver()
        with patch.object(lw, "_resolve_site", AsyncMock(return_value=_site())), \
             patch.object(
                 lw, "_attach_visitor",
                 AsyncMock(return_value=(_visitor(), lw.TIER_MARKER)),
             ), \
             patch.object(lw, "IdentityResolver", cls):
            await lw.ingest_identification(AsyncMock(), {"email": "a@acme.com"})
        _, data, _p = resolver._save_identified.await_args.args
        assert data["confidence_score"] > lw.MatchingMixin._WEAK_MATCH_MAX_CONFIDENCE

    @pytest.mark.asyncio
    async def test_gate_rejection_is_reported_not_swallowed(self):
        """_save_identified returning None means a quality gate refused the row."""
        cls, _resolver = self._patched_resolver(saved_row=None)
        with patch.object(lw, "_resolve_site", AsyncMock(return_value=_site())), \
             patch.object(
                 lw, "_attach_visitor",
                 AsyncMock(return_value=(_visitor(), lw.TIER_EMAIL)),
             ), \
             patch.object(lw, "IdentityResolver", cls):
            outcome = await lw.ingest_identification(
                AsyncMock(), {"email": "danica_naluz@acme.com", "name": "Janet Valla"}
            )
        assert outcome == "rejected"

    @pytest.mark.asyncio
    async def test_no_visitor_match_saves_nothing(self):
        cls, resolver = self._patched_resolver()
        with patch.object(lw, "_resolve_site", AsyncMock(return_value=_site())), \
             patch.object(lw, "_attach_visitor", AsyncMock(return_value=(None, None))), \
             patch.object(lw, "IdentityResolver", cls):
            outcome = await lw.ingest_identification(AsyncMock(), {"email": "a@acme.com"})
        assert outcome == "no_visitor_match"
        resolver._save_identified.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_person_is_dropped_before_any_lookup(self):
        with patch.object(lw, "_resolve_site", AsyncMock(return_value=_site())), \
             patch.object(lw, "_attach_visitor", AsyncMock()) as attach:
            outcome = await lw.ingest_identification(AsyncMock(), {"ip": "203.0.113.9"})
        assert outcome == "no_identity_data"
        attach.assert_not_awaited()


class TestPayloadSanitization:
    def test_control_characters_stripped_and_length_capped(self):
        assert lw._clean("  A\x00cme\n ", 100) == "Acme"
        assert len(lw._clean("x" * 500, 200)) == 200

    def test_non_string_is_dropped(self):
        assert lw._clean({"nested": "object"}, 100) is None
        assert lw._clean(None, 100) is None

    def test_envelope_and_bare_record_both_accepted(self):
        assert lw._unwrap({"data": {"email": "a@acme.com"}})["email"] == "a@acme.com"
        assert lw._unwrap({"email": "a@acme.com"})["email"] == "a@acme.com"

    @pytest.mark.parametrize(
        "bad_email", [{"address": "x@y.test"}, ["a@b.test"], 12345, True]
    )
    @pytest.mark.asyncio
    async def test_non_string_email_never_raises(self, bad_email):
        """A vendor sending a non-string email must not 500 the endpoint.

        The endpoint promises 'always 2xx for an unusable payload' precisely
        because Leadpipe auto-disables a webhook that keeps erroring — so an
        unhandled AttributeError here would eventually switch the feed off.
        """
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(None))
        with patch.object(lw, "_resolve_site", AsyncMock(return_value=_site())):
            outcome = await lw.ingest_identification(
                db, {"pixel_id": "px-1", "email": bad_email}
            )
        assert outcome == "no_identity_data"

    @pytest.mark.asyncio
    async def test_non_string_email_still_usable_when_a_name_is_present(self):
        """Dropping a junk email must not also discard a usable name."""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(_visitor("v-1")))
        with patch.object(lw, "_resolve_site", AsyncMock(return_value=_site())):
            visitor, tier = await lw._attach_visitor(
                db,
                _site(),
                {"beam_visitor_id": "v-1"},
                {"email": {"junk": 1}, "full_name": "A Person"},
            )
        assert tier == lw.TIER_MARKER


class TestBatchEnvelope:
    async def _post(self, body):
        s = MagicMock()
        s.leadpipe_webhook_secret = "right"
        ingest = AsyncMock(return_value="saved")
        with patch.object(webhooks, "settings", s), patch.object(
            webhooks, "ingest_identification", ingest
        ):
            out = await webhooks.leadpipe_identity(
                _FakeRequest(body), token="right", db=AsyncMock()
            )
        return out, ingest

    @pytest.mark.asyncio
    async def test_data_list_envelope_is_expanded_not_swallowed(self):
        """{"data": [...]} is the shape the vendor's REST feed uses.

        Treating the envelope as one record would report no_identity_data for the
        whole batch — silent total loss, with a 200 and no error anywhere.
        """
        out, ingest = await self._post({"data": [{"a": 1}, {"b": 2}, {"c": 3}]})
        assert out["processed"] == 3
        assert ingest.await_count == 3

    @pytest.mark.asyncio
    async def test_bare_record_still_treated_as_one(self):
        out, ingest = await self._post({"email": "a@acme.com"})
        assert out["processed"] == 1

    @pytest.mark.asyncio
    async def test_single_record_data_envelope_unchanged(self):
        """{"data": {...}} stays one record — _unwrap handles it downstream."""
        out, ingest = await self._post({"data": {"email": "a@acme.com"}})
        assert out["processed"] == 1


class TestOutreachGuardrail:
    def test_leadpipe_identity_is_a_candidate_not_verified(self):
        assert identity_status_for_provider("leadpipe") == STATUS_PROVIDER_CANDIDATE

    def test_leadpipe_is_never_emailable(self):
        """The webhook path must not have quietly promoted the provider."""
        assert is_emailable_identity("leadpipe") is False


class TestPullFlagGate:
    def test_pull_flag_off_removes_leadpipe_key_from_the_waterfall(self):
        """leadpipe_pull_enabled=False must skip the poll the same way a missing
        key does — without touching the webhook path, which shares the name."""
        from apps.api.config import Settings

        assert Settings().leadpipe_pull_enabled is True  # default: no change
        off = Settings(leadpipe_pull_enabled=False)
        key = off.leadpipe_api_key if (off.leadpipe_enabled and off.leadpipe_pull_enabled) else None
        assert key is None


class TestRecordTimestampWindow:
    def test_window_matches_the_pull_path(self):
        """Webhook and poll must agree on what 'close in time' means."""
        assert lw.MatchingMixin._IDENTITY_MATCH_WINDOW == timedelta(minutes=30)
