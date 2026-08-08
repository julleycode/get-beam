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
    build_org_family_kinds,
    classify_ip_org_kind,
    normalize_org_name,
    parse_as2org,
    parse_pfx2as,
    refresh_ip_org_dataset,
    resolve_row_kind,
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
        # WS-C: parse_as2org now returns (org_name_raw, organizationId) tuples.
        assert mapping[15169] == ("Google LLC", "GOGL-ARIN")
        assert mapping[8075] == ("MICROSOFT-CORP", "MSFT-ARIN")
        assert mapping[13335] == ("Cloudflare, Inc.", "CLOUD14-ARIN")
        assert mapping[3356] == ("Level 3 Communications", "LPL-141-ARIN")

    def test_the_type_field_discriminates_not_the_asn_key(self):
        """Both record types carry ``name``; only ``type`` separates them.

        The Organization record's own ``name`` ("Google LLC") must win over the
        ASN record's ``name`` ("GOOGLE") — proof the ASN record was routed by
        ``type: ASN`` and never mistaken for an org.
        """
        assert parse_as2org(AS2ORG_FIXTURE.encode())[15169] == (
            "Google LLC",
            "GOGL-ARIN",
        )

    def test_the_legacy_snake_case_shape_still_joins_via_the_fallback(self):
        """Pre-2024 dumps have no ``type`` and use ``org_id``/``organization_id``.

        Both fallbacks fire together here: the key-presence heuristic stands in
        for the missing ``type``, and the snake_case org-id spellings are still
        read. A non-empty result is the point — the camelCase fix ADDED a
        primary spelling, it did not drop the old one.
        """
        mapping = parse_as2org(LEGACY_SNAKE_CASE_FIXTURE.encode())
        assert mapping == {15169: ("Google LLC", "GOGL-ARIN")}

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


def _ratio_routes(total: int, with_org: int) -> dict[str, bytes]:
    """Build httpx routes with ``total`` offered prefixes, ``with_org`` of which
    have an org record — so ``skipped = total - with_org`` and the resulting
    ``skip_ratio = skipped / total``.

    Every prefix gets a unique /24 and a distinct ASN. ASNs are drawn from the
    reserved private-use range so they never collide with any real classifier
    data (RFC 6996 64512-65534).
    """
    pfx_lines = ["# routeviews-rv2-20260801-1200.pfx2as"]
    as2org_lines: list[str] = []
    for i in range(total):
        asn = 64512 + i
        pfx_lines.append(f"10.0.{i}.0\t24\t{asn}")
        if i < with_org:
            as2org_lines.append(
                json.dumps(_asn_rec(str(asn), f"NET-{asn}", f"ORG-{asn}-ARIN"))
            )
            as2org_lines.append(
                json.dumps(_org_rec(f"ORG-{asn}-ARIN", f"Acme {asn} Holdings"))
            )
    return {
        "pfx2as-creation.log": (
            b"2026-08-01 12:00:00\t2026/08/routeviews-rv2-20260801-1200.pfx2as.gz\n"
        ),
        "routeviews-rv2-20260801-1200.pfx2as.gz": gzip.compress(
            "\n".join(pfx_lines).encode()
        ),
        "as-organizations/": b'<a href="20260801.as-org2info.jsonl.gz">x</a>',
        "20260801.as-org2info.jsonl.gz": gzip.compress(
            "\n".join(as2org_lines).encode()
        ),
    }


class TestSkipRatioGuard:
    """WS-A: skip_ratio = skipped/prefixes; two-tier WARN then ABORT."""

    def _install(self, monkeypatch, routes):
        monkeypatch.setattr(
            ip_org_ingest.httpx, "AsyncClient", lambda **kw: _FakeClient(routes)
        )

    def _capture_warnings(self, monkeypatch) -> list[str]:
        events: list[str] = []
        real = ip_org_ingest.logger.warning

        def rec(event, *a, **kw):
            events.append(event)
            return real(event, *a, **kw)

        monkeypatch.setattr(ip_org_ingest.logger, "warning", rec)
        return events

    async def test_zero_skip_ratio_no_warn_no_abort(self, monkeypatch):
        self._install(monkeypatch, _ratio_routes(10, 10))
        warns = self._capture_warnings(monkeypatch)
        status = await refresh_ip_org_dataset(dry_run=True)
        assert status["status"] == "dry_run"
        assert status["skip_ratio"] == 0.0
        assert "ip_org_ingest_skip_ratio_high" not in warns

    async def test_healthy_baseline_ratio_no_warn(self, monkeypatch):
        # 13/100 = 0.13, the ~12.7 % healthy baseline — below the 0.25 warn floor.
        self._install(monkeypatch, _ratio_routes(100, 87))
        warns = self._capture_warnings(monkeypatch)
        status = await refresh_ip_org_dataset(dry_run=True)
        assert status["status"] == "dry_run"
        assert status["skip_ratio"] == 0.13
        assert "ip_org_ingest_skip_ratio_high" not in warns

    async def test_thirty_percent_warns_but_does_not_abort(self, monkeypatch):
        # 3/10 = 0.30: above warn (0.25), below abort (0.40). Proceeds.
        self._install(monkeypatch, _ratio_routes(10, 7))
        warns = self._capture_warnings(monkeypatch)
        status = await refresh_ip_org_dataset(dry_run=True)
        assert status["status"] == "dry_run"  # not aborted
        assert status["skip_ratio"] == 0.3
        assert "ip_org_ingest_skip_ratio_high" in warns
        assert "ip_org_ingest_skip_ratio_abort" not in warns

    async def test_forty_five_percent_aborts_and_never_swaps(self, monkeypatch):
        # 9/20 = 0.45: above abort (0.40). Must return status=error and never
        # reach _load_staging_and_swap (old data preserved).
        self._install(monkeypatch, _ratio_routes(20, 11))
        called = {"swap": False}

        async def _never(*a, **kw):
            called["swap"] = True

        monkeypatch.setattr(ip_org_ingest, "_load_staging_and_swap", _never)
        status = await refresh_ip_org_dataset(dry_run=False)
        assert status["status"] == "error"
        assert "skip ratio" in status["error"]
        assert status["skip_ratio"] == 0.45
        assert called["swap"] is False

    async def test_empty_prefixes_ratio_is_one_and_aborts(self, monkeypatch):
        # No parseable prefixes at all → ratio 1.0 → abort (the total-collapse
        # case the len(prefixes) denominator exists for).
        routes = _ratio_routes(0, 0)
        routes["routeviews-rv2-20260801-1200.pfx2as.gz"] = gzip.compress(
            b"# header only, no rows\n"
        )
        self._install(monkeypatch, routes)
        called = {"swap": False}

        async def _never(*a, **kw):
            called["swap"] = True

        monkeypatch.setattr(ip_org_ingest, "_load_staging_and_swap", _never)
        status = await refresh_ip_org_dataset(dry_run=False)
        assert status["status"] == "error"
        assert status["skip_ratio"] == 1.0
        assert called["swap"] is False


class TestOrgFamilyClassification:
    """WS-C: org-family fold is conservative-direction-only (Q6/R9).

    Every fixture ASN is drawn from the reserved private-use range 64512-65534
    (RFC 6996), guaranteed absent from any real APNIC per-AS population list, so
    WS-E's later eyeball_asns.json cannot flip a fixture and turn this gate red
    (P2-10). Reserved ASNs also sit outside _CDN_RELAY_ASNS / _DATACENTER_ASNS,
    so a fixture still exercises the org-token path as intended.
    """

    def test_a_telekom_shaped_sibling_promotes_its_org_sibling_to_eyeball(self):
        asn_orgs = {
            64512: ("Acme Telecom", "FAM1"),   # eyeball (token)
            64513: ("Acme Widgets Inc", "FAM1"),  # own kind org
        }
        fam = build_org_family_kinds(asn_orgs)
        assert fam["FAM1"] == "eyeball"
        # the org sibling inherits eyeball
        assert resolve_row_kind("org", fam["FAM1"]) == "eyeball"

    def test_an_org_sibling_does_not_demote_a_cdn_sibling_to_org(self):
        asn_orgs = {
            64514: ("Cloudflare Inc", "FAM2"),   # cdn (token)
            64515: ("Acme Widgets Inc", "FAM2"),  # org
        }
        fam = build_org_family_kinds(asn_orgs)
        assert fam["FAM2"] == "cdn"
        # the cdn sibling's own kind is cdn, so it is never touched (own != org)
        assert resolve_row_kind("cdn", fam["FAM2"]) == "cdn"

    def test_a_family_with_both_eyeball_and_cdn_leaves_both_unchanged(self):
        # R9 lateral-move guard: the eyeball ASN must NOT be overwritten to cdn.
        asn_orgs = {
            64516: ("Acme Telecom", "FAM3"),    # eyeball
            64517: ("Cloudflare Inc", "FAM3"),  # cdn
        }
        fam = build_org_family_kinds(asn_orgs)
        assert fam["FAM3"] == "cdn"  # family precedence
        assert resolve_row_kind("eyeball", fam["FAM3"]) == "eyeball"  # no lateral
        assert resolve_row_kind("cdn", fam["FAM3"]) == "cdn"

    def test_a_size_one_family_is_unchanged(self):
        asn_orgs = {64518: ("Acme Widgets Inc", "FAM4")}
        fam = build_org_family_kinds(asn_orgs)
        assert fam["FAM4"] == "org"
        assert resolve_row_kind("org", fam["FAM4"]) == "org"

    def test_nothing_is_ever_promoted_to_org(self):
        # A cdn/eyeball/datacenter row can never become org via the family pass.
        assert resolve_row_kind("cdn", "org") == "cdn"
        assert resolve_row_kind("eyeball", "org") == "eyeball"
        assert resolve_row_kind("datacenter", "org") == "datacenter"


class TestMultiAsnFamilyCounters:
    """WS-C / C5: multi_asn_families, fraction, family_reclassified via dry-run."""

    def _routes_for_families(self) -> dict[str, bytes]:
        # Through parse_as2org every ASN in a family shares ONE org NAME (from the
        # Organization record), so the eyeball/cdn TOKEN classification is
        # identical across a family — a real reclassification therefore requires
        # an ASN-SET difference. FAM-A's shared name classifies 'org', but member
        # AS14061 (DigitalOcean) is in _DATACENTER_ASNS, so the family folds to
        # 'datacenter' and its reserved-range org sibling (64513) is reclassified.
        # AS14061 is immune to WS-E's APNIC flip (P2-10): it is a datacenter ASN
        # and E3's direction guard keeps datacenter regardless of the eyeball set.
        # FAM-B: single reserved-ASN org family, no reclassify.
        pfx_lines = [
            "# routeviews-rv2-20260801-1200.pfx2as",
            "10.1.0.0\t24\t14061",
            "10.2.0.0\t24\t64513",
            "10.3.0.0\t24\t64518",
        ]
        as2org_lines = [
            json.dumps(_asn_rec("14061", "Acme Widgets Inc", "FAM-A")),
            json.dumps(_asn_rec("64513", "Acme Widgets Inc", "FAM-A")),
            json.dumps(_asn_rec("64518", "Beta Widgets Inc", "FAM-B")),
            json.dumps(_org_rec("FAM-A", "Acme Widgets Inc")),
            json.dumps(_org_rec("FAM-B", "Beta Widgets Inc")),
        ]
        return {
            "pfx2as-creation.log": (
                b"2026-08-01 12:00:00\t2026/08/routeviews-rv2-20260801-1200.pfx2as.gz\n"
            ),
            "routeviews-rv2-20260801-1200.pfx2as.gz": gzip.compress(
                "\n".join(pfx_lines).encode()
            ),
            "as-organizations/": b'<a href="20260801.as-org2info.jsonl.gz">x</a>',
            "20260801.as-org2info.jsonl.gz": gzip.compress(
                "\n".join(as2org_lines).encode()
            ),
        }

    async def test_counters_correct_on_a_known_family_layout(self, monkeypatch):
        monkeypatch.setattr(
            ip_org_ingest.httpx,
            "AsyncClient",
            lambda **kw: _FakeClient(self._routes_for_families()),
        )
        status = await refresh_ip_org_dataset(dry_run=True)
        assert status["multi_asn_families"] == 1  # FAM-A only
        # FAM-A has 2 of 3 ASNs -> 2/3 = 0.6667
        assert status["multi_asn_family_fraction"] == 0.6667
        # the FAM-A org sibling (64513) is reclassified org -> datacenter
        assert status["family_reclassified"] == 1


class TestApnicEyeballPreCheck:
    """WS-E / E3 / G17: APNIC numeric pre-check direction guard.

    load_eyeball_asns is imported by reference into ip_org_ingest, so we
    monkeypatch it there. Replacing the function (rather than clearing its cache)
    keeps these tests independent of the vendored file.
    """

    def _set_eyeball(self, monkeypatch, asns):
        monkeypatch.setattr(
            ip_org_ingest, "load_eyeball_asns", lambda: frozenset(asns)
        )

    def test_an_in_set_asn_is_eyeball(self, monkeypatch):
        self._set_eyeball(monkeypatch, {64520})
        # org-name would classify 'org', but the APNIC pre-check moves it eyeball.
        assert classify_ip_org_kind(64520, "Acme Widgets Inc") == "eyeball"

    def test_datacenter_and_cdn_win_over_the_apnic_set(self, monkeypatch):
        # Direction guard: infra classification beats population data even when
        # the ASN is in the eyeball set.
        self._set_eyeball(monkeypatch, {64521})
        assert classify_ip_org_kind(64521, "Cloudflare Inc") == "cdn"

    def test_an_out_of_set_asn_follows_the_unchanged_token_path(self, monkeypatch):
        self._set_eyeball(monkeypatch, set())
        assert classify_ip_org_kind(64522, "Acme Widgets Inc") == "org"
        # token path still fires for a carrier name absent from the set
        assert classify_ip_org_kind(64523, "Acme Telekom") == "eyeball"

    def test_the_discriminating_as_prefix_case(self, monkeypatch):
        # E6b/P2-11: an org string with NO cdn/datacenter token whose ASN IS in
        # _CDN_RELAY_ASNS must still classify 'cdn'. This is the ONLY case that
        # fails if the "AS{asn} " prefix is mis-built, because a Cloudflare-shaped
        # name would classify cdn via the org token regardless. AS13335 is
        # Cloudflare's ASN in _CDN_RELAY_ASNS.
        self._set_eyeball(monkeypatch, set())
        assert classify_ip_org_kind(13335, "Example Holdings") == "cdn"
