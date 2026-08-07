"""Unit gates over the IP→org ingest pipeline (parse / normalize / classify).

Pure-function coverage only: no network, no Postgres. The fetch layer is
exercised through mocked httpx so the fail-open contract is provable without a
live CAIDA download.
"""

import gzip
import json

import pytest

from apps.api.services import ip_org_ingest
from apps.api.services.ip_org_ingest import (
    classify_ip_org_kind,
    normalize_org_name,
    parse_as2org,
    parse_pfx2as,
    refresh_ip_org_dataset,
)

pytestmark = pytest.mark.unit


# Real-format snippet: prefix<TAB>len<TAB>asn, including a multi-origin line
# ("13335,209242") and an AS-set line ("64512_64513"), a comment, a blank line,
# an IPv6 row (must be skipped — IPv4 only), and a garbage ASN.
PFX2AS_FIXTURE = "\n".join(
    [
        "# routeviews-rv2-20260801-1200.pfx2as",
        "8.8.8.0\t24\t15169",
        "13.107.6.0\t24\t8075",
        "104.16.0.0\t13\t13335,209242",
        "192.0.2.0\t24\t64512_64513",
        "",
        "2001:db8::\t32\t65000",
        "10.0.0.0\t8\tNOT_AN_ASN",
        "203.0.113.0\t24\t3356",
    ]
)

# REAL CAIDA as-org2info record shapes, verified against a downloaded file:
# camelCase ``organizationId``, an explicit ``type`` discriminator, and the
# ``opaqueId`` / ``changed`` / ``source`` fields that ride along. Both record
# types carry a ``name``, which is exactly why ``type`` must do the
# discriminating. Do NOT "tidy" these into snake_case — that invented format was
# what let the parser skip all 1.1M prefixes while reporting success.
def _asn_rec(asn: str, name: str, org_id: str) -> dict:
    return {
        "asn": asn,
        "changed": "20240618",
        "name": name,
        "opaqueId": f"opaque-{asn}",
        "organizationId": org_id,
        "source": "ARIN",
        "type": "ASN",
    }


def _org_rec(org_id: str, name: str) -> dict:
    return {
        "changed": "20171130",
        "country": "US",
        "name": name,
        "organizationId": org_id,
        "source": "ARIN",
        "type": "Organization",
    }


AS2ORG_FIXTURE = "\n".join(
    [
        # Org records deliberately appear AFTER some of the ASN records that
        # reference them — the parser must do a two-pass join, not a streaming one.
        json.dumps(_asn_rec("15169", "GOOGLE", "GOGL-ARIN")),
        json.dumps(_asn_rec("8075", "MICROSOFT-CORP-MSN-AS-BLOCK", "MSFT-ARIN")),
        json.dumps(_org_rec("GOGL-ARIN", "Google LLC")),
        json.dumps(_org_rec("MSFT-ARIN", "MICROSOFT-CORP")),
        json.dumps(_asn_rec("13335", "CLOUDFLARENET", "CLOUD14-ARIN")),
        json.dumps(_org_rec("CLOUD14-ARIN", "Cloudflare, Inc.")),
        json.dumps(_asn_rec("3356", "LVLT-1", "LPL-141-ARIN")),
        json.dumps(_org_rec("LPL-141-ARIN", "Level 3 Communications")),
        # An ASN whose org record never appears — must be dropped, not crash.
        json.dumps(_asn_rec("64512", "MISSING-AS", "MISSING-ARIN")),
        "not json at all",
    ]
)

# The pre-2024 snake_case spelling, kept ONLY to document the fallback path.
LEGACY_SNAKE_CASE_FIXTURE = "\n".join(
    json.dumps(rec)
    for rec in [
        {"asn": "15169", "org_id": "GOGL-ARIN", "source": "ARIN"},
        {"organization_id": "GOGL-ARIN", "name": "Google LLC", "country": "US"},
    ]
)


class TestNormalizeOrgName:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("MICROSOFT-CORP", "microsoft"),
            ("Microsoft Corporation", "microsoft"),
            ("Microsoft, Inc.", "microsoft"),
            ("  Microsoft   Corp  ", "microsoft"),
            ("Google LLC", "google"),
            ("Cloudflare, Inc.", "cloudflare"),
            ("Acme Holdings GmbH", "acme holdings"),
            ("Foo Corp Ltd", "foo"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_normalization_table(self, raw, expected):
        assert normalize_org_name(raw) == expected

    def test_the_three_microsoft_spellings_collapse_to_one_key(self):
        keys = {
            normalize_org_name("MICROSOFT-CORP"),
            normalize_org_name("Microsoft Corporation"),
            normalize_org_name("Microsoft Inc"),
        }
        assert keys == {"microsoft"}

    def test_an_interior_suffix_token_is_not_stripped(self):
        # Trailing-only stripping: "Ltd Commodities" must survive intact.
        assert normalize_org_name("Ltd Commodities") == "ltd commodities"


class TestParsePfx2as:
    def test_it_parses_plain_rows(self):
        rows = dict(parse_pfx2as(PFX2AS_FIXTURE.encode()))
        assert rows["8.8.8.0/24"] == 15169
        assert rows["13.107.6.0/24"] == 8075

    def test_a_multi_origin_line_takes_the_first_asn(self):
        rows = dict(parse_pfx2as(PFX2AS_FIXTURE.encode()))
        assert rows["104.16.0.0/13"] == 13335

    def test_an_as_set_line_takes_the_first_asn(self):
        rows = dict(parse_pfx2as(PFX2AS_FIXTURE.encode()))
        assert rows["192.0.2.0/24"] == 64512

    def test_comments_blanks_ipv6_and_garbage_are_skipped(self):
        rows = dict(parse_pfx2as(PFX2AS_FIXTURE.encode()))
        assert "2001:db8::/32" not in rows
        assert "10.0.0.0/8" not in rows
        assert len(rows) == 5

    def test_an_empty_body_is_not_an_error(self):
        assert parse_pfx2as(b"") == []


class TestParseAs2org:
    def test_the_real_camelcase_shape_joins_correctly(self):
        """REGRESSION: the live file uses ``organizationId``, not ``org_id``.

        Reading only the snake_case spellings produced an empty org map, which
        joined to zero rows and skipped all 1,107,822 prefixes — while every
        fetch, decompress and parse step reported success. Nothing raised. This
        test is the guard: the ORG NAME must come back from a record set written
        exactly as CAIDA publishes it.
        """
        mapping = parse_as2org(AS2ORG_FIXTURE.encode())
        assert mapping[15169] == "Google LLC"
        assert mapping[8075] == "MICROSOFT-CORP"
        assert mapping[13335] == "Cloudflare, Inc."
        assert mapping[3356] == "Level 3 Communications"

    def test_the_type_field_discriminates_not_the_asn_key(self):
        """Both record types carry ``name``; only ``type`` separates them.

        The Organization record's own ``name`` ("Google LLC") must win over the
        ASN record's ``name`` ("GOOGLE") — proof the ASN record was routed by
        ``type: ASN`` and never mistaken for an org.
        """
        assert parse_as2org(AS2ORG_FIXTURE.encode())[15169] == "Google LLC"

    def test_the_legacy_snake_case_shape_still_joins_via_the_fallback(self):
        """Pre-2024 dumps have no ``type`` and use ``org_id``/``organization_id``.

        Both fallbacks fire together here: the key-presence heuristic stands in
        for the missing ``type``, and the snake_case org-id spellings are still
        read. A non-empty result is the point — the camelCase fix ADDED a
        primary spelling, it did not drop the old one.
        """
        mapping = parse_as2org(LEGACY_SNAKE_CASE_FIXTURE.encode())
        assert mapping == {15169: "Google LLC"}

    def test_an_unrecognized_org_id_spelling_yields_zero_orgs(self):
        """The fallback chain is finite: three spellings, then nothing.

        This is the shape of the original defect — an org-id key outside the
        known set leaves the org map empty, the join produces nothing, and the
        parse still "succeeds". Documented deliberately so the silence is a
        known property rather than a surprise.
        """
        unknown = "\n".join(
            json.dumps(rec)
            for rec in [
                {"asn": "15169", "orgIdentifier": "GOGL-ARIN", "type": "ASN"},
                {
                    "orgIdentifier": "GOGL-ARIN",
                    "name": "Google LLC",
                    "type": "Organization",
                },
            ]
        )
        assert parse_as2org(unknown.encode()) == {}

    def test_an_asn_whose_org_record_is_missing_is_dropped(self):
        assert 64512 not in parse_as2org(AS2ORG_FIXTURE.encode())

    def test_an_unparseable_line_does_not_abort_the_file(self):
        mapping = parse_as2org(AS2ORG_FIXTURE.encode())
        assert 3356 in mapping  # parsed after the garbage line's position


class TestClassifyIpOrgKind:
    def test_a_real_company_is_org(self):
        assert classify_ip_org_kind(65001, "Acme Widgets Inc") == "org"

    def test_a_cdn_is_cdn_not_org(self):
        # The fabricated-employer bug class: a CDN edge prefix must never be
        # served as somebody's employer.
        assert classify_ip_org_kind(13335, "Cloudflare, Inc.") == "cdn"

    def test_a_consumer_isp_is_eyeball_not_org(self):
        assert classify_ip_org_kind(7922, "Comcast Cable") == "eyeball"
        assert classify_ip_org_kind(65002, "Telenor Broadband") == "eyeball"

    def test_a_cloud_org_name_still_classifies_as_datacenter(self):
        # AS8075 is Azure, and the resolver's own token set already knows
        # "microsoft" is cloud compute — this path must NOT be re-decided here,
        # or the two classifiers drift.
        assert classify_ip_org_kind(8075, "MICROSOFT-CORP") == "datacenter"

    def test_a_hosting_provider_is_datacenter(self):
        assert classify_ip_org_kind(16509, "Amazon.com, Inc.") == "datacenter"


class _FakeResponse:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    """Minimal httpx.AsyncClient stand-in driven by a url→bytes map."""

    def __init__(self, routes: dict[str, bytes], fail: bool = False):
        self._routes = routes
        self._fail = fail

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url: str, **kwargs):
        if self._fail:
            raise RuntimeError("network down")
        for key, body in self._routes.items():
            if url.endswith(key) or url == key:
                return _FakeResponse(body)
        raise RuntimeError(f"unexpected url {url}")


def _routes() -> dict[str, bytes]:
    return {
        "pfx2as-creation.log": (
            b"2026-08-01 12:00:00\t2026/08/routeviews-rv2-20260801-1200.pfx2as.gz\n"
        ),
        "routeviews-rv2-20260801-1200.pfx2as.gz": gzip.compress(
            PFX2AS_FIXTURE.encode()
        ),
        "as-organizations/": b'<a href="20260801.as-org2info.jsonl.gz">x</a>',
        "20260801.as-org2info.jsonl.gz": gzip.compress(AS2ORG_FIXTURE.encode()),
    }


class TestRefreshDryRun:
    async def test_a_dry_run_reports_counts_and_writes_nothing(self, monkeypatch):
        monkeypatch.setattr(
            ip_org_ingest.httpx,
            "AsyncClient",
            lambda **kw: _FakeClient(_routes()),
        )
        status = await refresh_ip_org_dataset(dry_run=True)
        assert status["status"] == "dry_run"
        assert status["prefixes"] == 5
        # 8.8.8.0/24, 13.107.6.0/24, 104.16.0.0/13, 203.0.113.0/24 join; the
        # AS-set row's ASN has no org record and is skipped.
        assert status["rows"] == 4
        assert status["skipped"] == 1
        assert status["dataset_date"] == "2026-08-01"

    async def test_a_fetch_failure_is_fail_open_not_an_exception(self, monkeypatch):
        monkeypatch.setattr(
            ip_org_ingest.httpx,
            "AsyncClient",
            lambda **kw: _FakeClient({}, fail=True),
        )
        status = await refresh_ip_org_dataset(dry_run=True)
        assert status["status"] == "error"
        assert "network down" in status["error"]

    async def test_a_missing_creation_log_entry_is_fail_open(self, monkeypatch):
        routes = _routes()
        routes["pfx2as-creation.log"] = b"# nothing useful here\n"
        monkeypatch.setattr(
            ip_org_ingest.httpx, "AsyncClient", lambda **kw: _FakeClient(routes)
        )
        status = await refresh_ip_org_dataset(dry_run=True)
        assert status["status"] == "error"
