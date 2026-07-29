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
    def _db(returned_id=uuid.uuid4()):
        db = AsyncMock()
        result = Mock()
        result.scalar_one_or_none = Mock(return_value=returned_id)
        db.execute = AsyncMock(return_value=result)
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
    async def test_undecodable_marker_writes_nothing(self, key):
        db = self._db()
        written = await agent_marker.record_marker_handoff(
            db, site_id="site_1", visitor_id="v1", marker="forged"
        )
        assert written is False
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_write_failure_is_swallowed_and_logs_keys_only(self, key, monkeypatch):
        """This runs on the ingest hot path — a failure must never reach the 204,
        and must never log the marker or the visitor."""
        db = self._db()
        db.execute = AsyncMock(side_effect=RuntimeError("boom"))
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
