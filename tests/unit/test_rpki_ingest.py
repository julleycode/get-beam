"""RPKI validator-dump parsing and the streamed size cap (AC3.4). No network, no DB.

**Fixture provenance.** The ROA shape below is excerpted from the live Cloudflare
dump ``https://rpki.cloudflare.com/rpki.json``, fetched 2026-08-07: 102,878,317
bytes, 987,997 ROAs, first entries::

    {"asn": 13335, "prefix": "1.0.0.0/24",  "maxLength": 24, "ta": "apnic", "expires": 1786630651}
    {"asn": 18144, "prefix": "1.0.64.0/18", "maxLength": 18, "ta": "apnic", "expires": 1786715361}

Worth recording: the LIVE file spells ``asn`` as a plain integer, while the
format's documentation (and this plan's own sample) shows ``"AS13335"``. The
parser accepts both, but the fixtures below lead with the live form — the Phase 1
``organizationId`` bug came from trusting a documented spelling over a downloaded
one.

That measured 98 MB also justifies the guard: it is the reason the body is
streamed with an abort rather than read and then measured.
"""

import json

import httpx
import pytest

from apps.api.services import rpki_ingest
from apps.api.services.rpki_ingest import (
    PayloadTooLarge,
    _fetch_capped,
    parse_rpki_json,
    refresh_rpki_roas,
)

pytestmark = pytest.mark.unit

# Verbatim live entries.
LIVE_ROAS = {
    "roas": [
        {"asn": 13335, "prefix": "1.0.0.0/24", "maxLength": 24, "ta": "apnic",
         "expires": 1786630651},
        {"asn": 18144, "prefix": "1.0.64.0/18", "maxLength": 18, "ta": "apnic",
         "expires": 1786715361},
    ]
}


class TestParsing:
    def test_the_live_integer_asn_spelling_parses(self):
        got = parse_rpki_json(json.dumps(LIVE_ROAS).encode())
        assert got == [
            {"prefix": "1.0.0.0/24", "asn": 13335, "max_length": 24},
            {"prefix": "1.0.64.0/18", "asn": 18144, "max_length": 18},
        ]

    def test_the_documented_as_prefixed_spelling_also_parses(self):
        payload = json.dumps(
            {"roas": [{"asn": "AS13335", "prefix": "1.0.0.0/24", "maxLength": 24}]}
        ).encode()
        assert parse_rpki_json(payload) == [
            {"prefix": "1.0.0.0/24", "asn": 13335, "max_length": 24}
        ]

    def test_a_four_byte_asn_survives_parsing(self):
        """ASNs are 32-bit UNSIGNED (RFC 6793) — the top of the space is real.

        Verbatim from the live dump; 17 of its 755,538 IPv4 ROAs carry an ASN
        above int32, and an earlier INTEGER column rejected the whole load on
        them. Dropping such a ROA would be worse than losing it: with the
        authorizing ROA gone but a covering one present, ``validate_origin``
        returns INVALID and a legitimate announcement gets scored as disputed.
        """
        payload = json.dumps(
            {
                "roas": [
                    {"asn": 4202202105, "prefix": "49.236.202.0/24", "maxLength": 24},
                    {"asn": 4294967294, "prefix": "103.138.210.0/24", "maxLength": 26},
                ]
            }
        ).encode()
        got = parse_rpki_json(payload)
        assert [r["asn"] for r in got] == [4202202105, 4294967294]
        assert max(r["asn"] for r in got) > 2_147_483_647

    def test_the_roa_asn_column_is_wide_enough_for_a_four_byte_asn(self):
        """The parser is only half the fix — the COLUMN has to hold it too."""
        from sqlalchemy import BigInteger

        from apps.api.models.rpki_roa import RpkiRoa

        assert isinstance(RpkiRoa.__table__.c.asn.type, BigInteger)

    def test_ipv6_entries_are_skipped(self):
        payload = json.dumps(
            {"roas": [{"asn": 13335, "prefix": "2606:4700::/32", "maxLength": 48}]}
        ).encode()
        assert parse_rpki_json(payload) == []

    @pytest.mark.parametrize(
        "entry",
        [
            {"asn": 1, "prefix": "1.0.0.0/24"},          # no maxLength
            {"asn": 1, "maxLength": 24},                  # no prefix
            {"asn": "notanumber", "prefix": "1.0.0.0/24", "maxLength": 24},
            {"asn": 1, "prefix": 12345, "maxLength": 24},
            "not-a-dict",
        ],
    )
    def test_a_malformed_entry_is_skipped_not_fatal(self, entry):
        payload = json.dumps({"roas": [entry, LIVE_ROAS["roas"][0]]}).encode()
        assert parse_rpki_json(payload) == [
            {"prefix": "1.0.0.0/24", "asn": 13335, "max_length": 24}
        ]

    @pytest.mark.parametrize(
        "payload", [b"", b"not json", b"[]", b'{"roas": "nope"}', b'{"other": []}']
    )
    def test_an_unusable_document_yields_an_empty_list_not_an_exception(self, payload):
        assert parse_rpki_json(payload) == []


class _FakeStream:
    """Minimal httpx.stream() context manager yielding scripted chunks."""

    def __init__(self, chunks):
        self._chunks = chunks

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def raise_for_status(self):
        return None

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


class _FakeClient:
    def __init__(self, chunks):
        self._chunks = chunks
        self.consumed = 0

    def stream(self, _method, _url, **_kw):
        outer = self

        class _Counting(_FakeStream):
            async def aiter_bytes(self):
                for chunk in outer._chunks:
                    outer.consumed += len(chunk)
                    yield chunk

        return _Counting(self._chunks)


class TestMaxBytesGuard:
    """AC3.4 / G16 — abort WHILE streaming, never read-then-check."""

    async def test_max_bytes_aborts_the_fetch_once_the_cap_is_passed(self):
        client = _FakeClient([b"x" * 100] * 100)  # 10 KB available
        with pytest.raises(PayloadTooLarge):
            await _fetch_capped(client, "http://example.invalid", max_bytes=250)
        # The abort is the point: it must not have drained the whole body first.
        assert client.consumed <= 300, (
            f"read {client.consumed} bytes past a 250-byte cap — "
            "the guard is checking after the fact, not while streaming"
        )

    async def test_max_bytes_lets_a_body_under_the_cap_through_whole(self):
        client = _FakeClient([b"ab", b"cd"])
        assert await _fetch_capped(client, "http://example.invalid", 100) == b"abcd"

    async def test_max_bytes_exceeded_is_fail_open_and_never_parsed(
        self, monkeypatch
    ):
        """Old ROA data must survive; json.loads must never be reached."""
        called = {"parsed": False}

        def _boom(_payload):
            called["parsed"] = True
            raise AssertionError("parse_rpki_json must not run on an oversize body")

        monkeypatch.setattr(rpki_ingest, "parse_rpki_json", _boom)

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            def stream(self, *_a, **_kw):
                return _FakeStream([b"x" * 1024] * 64)

        monkeypatch.setattr(httpx, "AsyncClient", lambda **_kw: _Client())
        monkeypatch.setattr(rpki_ingest.settings, "ip_org_rpki_max_bytes", 1024)

        status = await refresh_rpki_roas(dry_run=True)
        assert status == {
            "status": "error",
            "error": "rpki payload exceeded max bytes",
        }
        assert called["parsed"] is False

    async def test_max_bytes_default_is_two_hundred_megabytes(self):
        """The live file is ~98 MB, so the cap must leave real headroom."""
        assert rpki_ingest.settings.ip_org_rpki_max_bytes == 209_715_200


class TestFailOpen:
    async def test_a_fetch_error_returns_a_status_dict_not_an_exception(
        self, monkeypatch
    ):
        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            def stream(self, *_a, **_kw):
                raise httpx.ConnectError("down")

        monkeypatch.setattr(httpx, "AsyncClient", lambda **_kw: _Client())
        status = await refresh_rpki_roas(dry_run=True)
        assert status["status"] == "error"

    async def test_a_dry_run_reports_counts_and_writes_nothing(self, monkeypatch):
        body = json.dumps(LIVE_ROAS).encode()

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            def stream(self, *_a, **_kw):
                return _FakeStream([body])

        monkeypatch.setattr(httpx, "AsyncClient", lambda **_kw: _Client())
        status = await refresh_rpki_roas(dry_run=True)
        assert status["status"] == "dry_run"
        assert status["roas"] == 2
