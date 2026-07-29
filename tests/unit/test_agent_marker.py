"""Unit tests for the per-fetch link marker (Handoff Detection F2).

Covers the round trip (mint → URL → read back), the cases that must NOT produce
an attribution (forged, expired, foreign host, cross-surface leakage), and the
emailability separation tripwire.

All DB interaction is mocked — no live DB.
"""

import uuid
from unittest.mock import AsyncMock, Mock

import pytest
from cryptography.fernet import Fernet

from apps.api.services import agent_marker
from apps.api.services.agent_marker import (
    MARKER_PARAM,
    decode_marker,
    marker_from_url,
    mint_marker,
    stamp_marker,
)


@pytest.fixture
def key(monkeypatch):
    """A real Fernet key — the marker is genuinely encrypted in these tests."""
    from apps.api.services import link_decorator

    monkeypatch.setattr(link_decorator.settings, "encryption_key", Fernet.generate_key().decode())


class TestRoundTrip:
    @pytest.mark.unit
    def test_mint_then_decode_recovers_the_fetch_id(self, key):
        fetch_id = uuid.uuid4()
        token = mint_marker(fetch_id)
        assert token
        assert decode_marker(token) == fetch_id

    @pytest.mark.unit
    def test_marker_survives_the_full_url_round_trip(self, key):
        """Mint → stamped onto an offer URL → read back off the landing URL, the
        path the pixel actually delivers."""
        fetch_id = uuid.uuid4()
        token = mint_marker(fetch_id)
        landing = stamp_marker("https://acme.com/pricing", token, "https://acme.com")
        assert decode_marker(marker_from_url(landing)) == fetch_id

    @pytest.mark.unit
    def test_no_fetch_id_mints_nothing(self, key):
        """An unrecognized agent yields no fetch row, so there is nothing to name."""
        assert mint_marker(None) is None

    @pytest.mark.unit
    def test_no_key_configured_degrades_to_unmarked(self, monkeypatch):
        from apps.api.services import link_decorator

        monkeypatch.setattr(link_decorator.settings, "encryption_key", "")
        assert mint_marker(uuid.uuid4()) is None
        assert decode_marker("anything") is None


class TestMarkerIsNotTrusted:
    """Every unusable marker must degrade to "no link", never to a wrong link."""

    @pytest.mark.parametrize(
        "token", [None, "", "garbage", "gAAAAABmZm-not-a-real-token"]
    )
    @pytest.mark.unit
    def test_malformed_or_forged_marker_decodes_to_nothing(self, key, token):
        assert decode_marker(token) is None

    @pytest.mark.unit
    def test_marker_from_a_different_key_is_rejected(self, key, monkeypatch):
        """A token minted elsewhere must not name a fetch in this deployment."""
        foreign = Fernet(Fernet.generate_key()).encrypt(
            str(uuid.uuid4()).encode()
        ).decode()
        assert decode_marker(foreign) is None

    @pytest.mark.unit
    def test_expired_marker_is_rejected(self, key, monkeypatch):
        """A forwarded link resurfacing weeks later is not the human who acted on
        the agent's answer, so it must not attribute one."""
        token = mint_marker(uuid.uuid4())
        monkeypatch.setattr(agent_marker, "MARKER_TTL_SECONDS", -1)
        assert decode_marker(token) is None


class TestDecodeReason:
    """The reason is what makes a zero-link dashboard diagnosable, so the split
    between 'worked but old' and 'never valid' has to be real."""

    @pytest.mark.unit
    def test_ok(self, key):
        fetch_id = uuid.uuid4()
        assert agent_marker.decode_marker_with_reason(mint_marker(fetch_id)) == (
            fetch_id,
            "ok",
        )

    @pytest.mark.unit
    def test_absent(self, key):
        assert agent_marker.decode_marker_with_reason(None)[1] == "absent"
        assert agent_marker.decode_marker_with_reason("")[1] == "absent"

    @pytest.mark.unit
    def test_expired_is_not_reported_as_invalid(self, key, monkeypatch):
        """An expired marker proves the whole chain works and the click was just
        old — the opposite operational conclusion from a forged one."""
        token = mint_marker(uuid.uuid4())
        monkeypatch.setattr(agent_marker, "MARKER_TTL_SECONDS", -1)
        assert agent_marker.decode_marker_with_reason(token) == (None, "expired")

    @pytest.mark.unit
    def test_forged_and_foreign_key_are_invalid(self, key):
        assert agent_marker.decode_marker_with_reason("garbage")[1] == "invalid"
        foreign = (
            Fernet(Fernet.generate_key()).encrypt(str(uuid.uuid4()).encode()).decode()
        )
        assert agent_marker.decode_marker_with_reason(foreign)[1] == "invalid"

    @pytest.mark.unit
    def test_no_key(self, monkeypatch):
        from apps.api.services import link_decorator

        monkeypatch.setattr(link_decorator.settings, "encryption_key", "")
        assert agent_marker.decode_marker_with_reason("x")[1] == "no_key"

    @pytest.mark.unit
    def test_valid_token_that_is_not_a_uuid_is_malformed(self, key):
        from apps.api.services.link_decorator import _get_fernet

        token = _get_fernet().encrypt(b"not-a-uuid").decode()
        assert agent_marker.decode_marker_with_reason(token) == (None, "malformed")


class TestDiagnosticLogging:
    """Zero links must be diagnosable from logs alone — the precedent the
    correlation sweep already set for itself."""

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_seen_is_logged_even_when_the_marker_is_unusable(
        self, key, monkeypatch
    ):
        info = Mock()
        monkeypatch.setattr(agent_marker.logger, "info", info)
        db = TestHandoffWrite._db()

        await agent_marker.record_marker_handoff(
            db, site_id="site_1", visitor_id="visitor-abcdef123", marker="garbage"
        )

        event, kwargs = info.call_args.args[0], info.call_args.kwargs
        assert event == "agent_marker_seen"
        assert kwargs["decoded"] is False
        assert kwargs["reason"] == "invalid"
        # PII guard: truncated visitor, and never the marker itself.
        assert kwargs["visitor_id"] == "visitor-"
        assert "garbage" not in str(kwargs)

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_success_path_logs_both_events(self, key, monkeypatch):
        events = []
        monkeypatch.setattr(
            agent_marker.logger, "info", lambda e, **kw: events.append((e, kw))
        )
        db = TestHandoffWrite._db()

        await agent_marker.record_marker_handoff(
            db, site_id="site_1", visitor_id="v1", marker=mint_marker(uuid.uuid4())
        )

        names = [e for e, _ in events]
        assert names == ["agent_marker_seen", "agent_marker_handoff_written"]
        assert dict(events[0][1])["reason"] == "ok"
        assert dict(events[1][1])["written"] is True

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_already_linked_is_logged_as_written_false_not_an_error(
        self, key, monkeypatch
    ):
        """Someone else clicked the shared link first. Expected, not a failure —
        it must stay visible instead of looking like a silent drop."""
        warn = Mock()
        events = []
        monkeypatch.setattr(agent_marker.logger, "warning", warn)
        monkeypatch.setattr(
            agent_marker.logger, "info", lambda e, **kw: events.append((e, kw))
        )
        db = TestHandoffWrite._db(returned_id=None)

        written = await agent_marker.record_marker_handoff(
            db, site_id="site_1", visitor_id="v2", marker=mint_marker(uuid.uuid4())
        )

        assert written is False
        warn.assert_not_called()
        assert dict(events[-1][1])["written"] is False


class TestStampScope:
    @pytest.mark.unit
    def test_foreign_host_is_never_stamped(self, key):
        """Only the customer's own pages run the Beam pixel, so a marker anywhere
        else is a token handed out for nothing."""
        url = "https://gumroad.com/l/thing"
        assert stamp_marker(url, "tok", "https://acme.com") == url

    @pytest.mark.unit
    def test_subdomain_of_the_site_is_stamped(self, key):
        out = stamp_marker("https://shop.acme.com/x", "tok", "https://acme.com")
        assert f"{MARKER_PARAM}=tok" in out

    @pytest.mark.unit
    def test_existing_query_is_preserved(self, key):
        out = stamp_marker("https://acme.com/x?a=1", "tok", "https://acme.com")
        assert "a=1" in out and f"{MARKER_PARAM}=tok" in out

    @pytest.mark.unit
    def test_already_marked_url_is_left_alone(self, key):
        url = f"https://acme.com/x?{MARKER_PARAM}=first"
        assert stamp_marker(url, "second", "https://acme.com") == url

    @pytest.mark.parametrize("bad", [None, "", "not a url"])
    @pytest.mark.unit
    def test_unusable_offer_url_never_breaks_the_feed(self, key, bad):
        assert stamp_marker(bad, "tok", "https://acme.com") == bad

    @pytest.mark.unit
    def test_missing_site_url_stamps_nothing(self, key):
        url = "https://acme.com/x"
        assert stamp_marker(url, "tok", None) == url


class TestMarkerFromUrl:
    @pytest.mark.parametrize(
        "url", [None, "", "https://acme.com/x", "https://acme.com/x?other=1"]
    )
    @pytest.mark.unit
    def test_absent_marker_reads_as_none(self, url):
        assert marker_from_url(url) is None

    @pytest.mark.unit
    def test_marker_is_read_alongside_other_params(self):
        url = f"https://acme.com/x?utm_source=chatgpt&{MARKER_PARAM}=tok&a=1"
        assert marker_from_url(url) == "tok"


class TestHandoffWrite:
    @staticmethod
    def _db(returned_id="__new__", owned=True):
        """Two executes happen on the write path — the ownership check, then the
        insert — so they need distinct results."""
        db = AsyncMock()
        ownership = Mock()
        ownership.scalar_one_or_none = Mock(
            return_value=uuid.uuid4() if owned else None
        )
        insert = Mock()
        insert.scalar_one_or_none = Mock(
            return_value=uuid.uuid4() if returned_id == "__new__" else returned_id
        )
        db.execute = AsyncMock(side_effect=[ownership, insert])
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        return db

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_valid_marker_writes_a_high_confidence_link(self, key):
        fetch_id = uuid.uuid4()
        token = mint_marker(fetch_id)
        db = self._db()

        written = await agent_marker.record_marker_handoff(
            db, site_id="site_1", visitor_id="v1", marker=token
        )

        assert written is True
        db.commit.assert_awaited_once()
        params = db.execute.await_args.args[0].compile().params
        assert params["agent_fetch_event_id"] == fetch_id
        assert params["confidence"] == "high"
        assert params["method"] == "marker"
        assert params["site_id"] == "site_1"
        assert params["visitor_id"] == "v1"

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_marker_upgrades_a_temporal_guess_but_not_another_marker(self, key):
        """The sweep's link is a probabilistic guess; this is the ground truth it
        was approximating, so it replaces it. A second marker must NOT replace the
        first, or a shared link would re-attribute the fetch to the latest clicker.
        """
        from sqlalchemy.dialects import postgresql

        token = mint_marker(uuid.uuid4())
        db = self._db()
        await agent_marker.record_marker_handoff(
            db, site_id="site_1", visitor_id="v1", marker=token
        )

        sql = str(
            db.execute.await_args.args[0].compile(dialect=postgresql.dialect())
        )
        assert "ON CONFLICT" in sql and "DO UPDATE" in sql
        # The guard that makes "temporal yes, marker no" structural.
        assert "method !=" in sql.replace("<>", "!=")

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_marker_naming_another_tenants_fetch_is_refused(self, key):
        """Decoding only proves this deployment minted the marker, not that it
        minted it for THIS site. A marker lifted from another site's public feed
        must not file a link — it would mis-attribute, and would also consume the
        owning site's one allowed link for that fetch."""
        db = self._db(owned=False)

        written = await agent_marker.record_marker_handoff(
            db, site_id="site_other", visitor_id="v1", marker=mint_marker(uuid.uuid4())
        )

        assert written is False
        # Only the ownership SELECT ran — no insert was attempted.
        assert db.execute.await_count == 1
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_foreign_fetch_is_logged_with_its_own_reason(self, key, monkeypatch):
        events = []
        monkeypatch.setattr(
            agent_marker.logger, "info", lambda e, **kw: events.append((e, kw))
        )
        await agent_marker.record_marker_handoff(
            self._db(owned=False),
            site_id="site_other",
            visitor_id="v1",
            marker=mint_marker(uuid.uuid4()),
        )
        assert events[0][0] == "agent_marker_seen"
        assert dict(events[0][1])["reason"] == "foreign_site"
        assert dict(events[0][1])["decoded"] is False

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_undecodable_marker_writes_nothing(self, key):
        db = self._db()
        written = await agent_marker.record_marker_handoff(
            db, site_id="site_1", visitor_id="v1", marker="forged"
        )
        assert written is False
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_insert_failure_is_swallowed_and_logs_keys_only(self, key, monkeypatch):
        """This runs on the ingest hot path — a failure must never reach the 204,
        and must never log the marker or the visitor."""
        db = self._db()
        ownership = Mock()
        ownership.scalar_one_or_none = Mock(return_value=uuid.uuid4())
        db.execute = AsyncMock(side_effect=[ownership, RuntimeError("boom")])
        warn = Mock()
        monkeypatch.setattr(agent_marker.logger, "warning", warn)

        written = await agent_marker.record_marker_handoff(
            db, site_id="site_1", visitor_id="secret-visitor", marker=mint_marker(uuid.uuid4())
        )

        assert written is False
        db.rollback.assert_awaited_once()
        _args, kwargs = warn.call_args
        assert set(kwargs.keys()) == {"site_id"}
        assert "secret-visitor" not in str(kwargs)

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_ownership_check_failure_never_reaches_the_caller(
        self, key, monkeypatch
    ):
        """The tenancy check is a database round trip on the ingest path. If it
        raises, the pageview must still succeed — unverified simply means no
        link, and the temporal sweep can still match later."""
        db = self._db()
        db.execute = AsyncMock(side_effect=RuntimeError("boom"))
        events = []
        monkeypatch.setattr(agent_marker.logger, "warning", Mock())
        monkeypatch.setattr(
            agent_marker.logger, "info", lambda e, **kw: events.append((e, kw))
        )

        written = await agent_marker.record_marker_handoff(
            db, site_id="site_1", visitor_id="v1", marker=mint_marker(uuid.uuid4())
        )

        assert written is False
        db.rollback.assert_awaited_once()
        assert dict(events[0][1])["reason"] == "check_failed"


class TestEmailabilitySeparation:
    @pytest.mark.unit
    def test_marker_module_imports_no_identity_write_path(self):
        """Absence tripwire, mirroring test_handoff_emailability_separation.py: a
        handoff link is attribution metadata and must never be able to make anyone
        contactable."""
        from pathlib import Path

        source = Path(agent_marker.__file__).read_text(encoding="utf-8")
        for forbidden in (
            "IdentifiedVisitor",
            "is_emailable_identity",
            "source_agent_visit_id",
            "identity_resolver",
        ):
            assert forbidden not in source, f"{forbidden} must not appear in agent_marker"
