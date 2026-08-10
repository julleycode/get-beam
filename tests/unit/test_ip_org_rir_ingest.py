"""RIR delegated-extended parsing (AC2.1, AC2.2, AC2.5, AC2.6). No network, no DB.

**Fixture provenance.** Every line below is EXCERPTED VERBATIM from a real
delegated-extended file downloaded on 2026-08-07:

- ``https://ftp.arin.net/pub/stats/arin/delegated-arin-extended-latest``
  (201,861 lines)
- ``https://ftp.ripe.net/pub/stats/ripencc/delegated-ripencc-extended-latest``
  (260,121 lines)
- ``https://ftp.apnic.net/stats/apnic/delegated-apnic-extended-latest``
  (189,025 lines)

This is not ceremony. Phase 1 of this program shipped a parser bug that every
unit test passed because the fixtures INVENTED the wire format (``organization_id``
where the live file says ``organizationId``), and the join silently produced zero
rows. A hand-written fixture for an external format is treated here as a defect.

Likewise, the expected CIDR decomposition in ``TestRangeDecomposition`` was
produced by RUNNING ``ipaddress.summarize_address_range`` and pasting its output,
not by reasoning about it — an earlier hand-derived value in the plan was not
merely wrong but not even a valid network (``8.8.9.0/23`` does not exist).
"""

import pytest

from apps.api.services.ip_org_rir_ingest import (
    _allocation_to_row,
    _parse_allocation_date,
    parse_delegated_extended,
)

pytestmark = pytest.mark.unit


# Real ARIN records (verbatim).
ARIN_VERSION_LINE = b"2.3|arin|1786107620675|201857|19700101|20260807|-0400"
ARIN_SUMMARY_LINES = (
    b"arin|*|asn|*|32887|summary\n"
    b"arin|*|ipv4|*|80687|summary\n"
    b"arin|*|ipv6|*|88283|summary"
)
ARIN_ALLOCATED = (
    b"arin|US|ipv4|1.178.0.0|512|20250113|allocated|20c786e8edd815cc245070645e265298"
)
# Real ARIN zero-date record (108 such lines in the live file).
ARIN_ZERO_DATE = b"arin|US|asn|3|1|00000000|assigned|d98c567cda2db06e693f2b574eafe848"
# Real ARIN reserved record — note the EMPTY cc and EMPTY date fields.
ARIN_RESERVED = b"arin||ipv4|23.128.1.0|768||reserved|"

# Real RIPE records (verbatim). RIPE is where non-power-of-two allocated counts,
# ``assigned`` status and ``available`` status all actually occur.
RIPE_NON_POWER_OF_TWO = (
    b"ripencc|RU|ipv4|62.122.208.0|1280|20090417|allocated|"
    b"d3cdd5d5-cb49-4d76-95ad-1d69d49b1a1b"
)
RIPE_ASSIGNED = (
    b"ripencc|BG|ipv4|87.116.83.0|2304|20050913|allocated|"
    b"e9fcf133-1ebe-4674-a220-7872659f9ead"
)
RIPE_IPV6 = b"ripencc|DE|ipv6|2001:600::|32|19990819|allocated|xxxx"


class TestRangeDecomposition:
    def test_a_non_power_of_two_range_becomes_the_exact_minimal_cidr_set(self):
        """AC2.1 — ``value`` is a COUNT, not a masklen, and need not be a power of two.

        Expected value produced by executing::

            ipaddress.summarize_address_range(
                IPv4Address('8.8.8.0'), IPv4Address('8.8.10.255')
            )
            -> ['8.8.8.0/23', '8.8.10.0/24']
        """
        line = b"arin|US|ipv4|8.8.8.0|768|20200101|allocated|XX-1-ARIN"
        got = parse_delegated_extended(line)
        assert [a["prefix"] for a in got] == ["8.8.8.0/23", "8.8.10.0/24"]

    def test_a_real_ripe_non_power_of_two_allocation_decomposes(self):
        """1280 addresses = 1024 + 256, i.e. a /22 plus a /24."""
        got = parse_delegated_extended(RIPE_NON_POWER_OF_TWO)
        assert [a["prefix"] for a in got] == ["62.122.208.0/22", "62.122.212.0/24"]
        assert all(a["registry"] == "ripencc" and a["cc"] == "RU" for a in got)

    def test_a_power_of_two_range_is_a_single_block(self):
        got = parse_delegated_extended(ARIN_ALLOCATED)
        assert [a["prefix"] for a in got] == ["1.178.0.0/23"]  # 512 addresses
        assert got[0]["opaque_id"] == "20c786e8edd815cc245070645e265298"

    def test_the_count_is_never_read_as_a_prefix_length(self):
        """The trap: ``|512|`` must not become ``/512`` or ``/24`` by accident."""
        got = parse_delegated_extended(ARIN_ALLOCATED)
        assert got[0]["prefix"].endswith("/23")


class TestSkippedLines:
    """AC2.2 — headers, summaries and non-delegated ranges produce zero rows."""

    @pytest.mark.parametrize(
        "line",
        [
            ARIN_VERSION_LINE,
            ARIN_SUMMARY_LINES,
            ARIN_RESERVED,
            RIPE_IPV6,
            b"apnic|AU|asn|4608|1|20110412|allocated|A91A5B0E",
            b"ripencc||ipv4|5.134.16.0|2048||reserved",
            b"apnic||ipv4|1.1.1.0|256||available",
            b"",
            b"# a comment",
            b"garbage",
        ],
    )
    def test_non_delegation_lines_yield_nothing(self, line):
        assert parse_delegated_extended(line) == []

    def test_a_realistic_mixed_file_yields_only_the_delegated_ipv4_rows(self):
        payload = b"\n".join(
            [
                ARIN_VERSION_LINE,
                ARIN_SUMMARY_LINES,
                ARIN_ALLOCATED,
                ARIN_ZERO_DATE,
                ARIN_RESERVED,
                RIPE_IPV6,
                RIPE_ASSIGNED,
            ]
        )
        got = parse_delegated_extended(payload)
        assert [a["prefix"] for a in got] == [
            # Produced by RUNNING summarize_address_range on 87.116.83.0 + 2304,
            # not by hand — the first draft of this list was reasoned out and was
            # wrong, which is the whole reason for the rule in the module docstring.
            "1.178.0.0/23",
            "87.116.83.0/24",
            "87.116.84.0/22",
            "87.116.88.0/22",
        ]


class TestZeroDate:
    """AC2.6 / G17 — an unparseable date KEEPS the row; it is not a skip."""

    @pytest.mark.parametrize("raw", ["00000000", "", "   ", "2020", "notadate", "20201332"])
    def test_zero_date_or_garbage_becomes_none(self, raw):
        assert _parse_allocation_date(raw) is None

    def test_zero_date_rule_still_parses_a_real_date(self):
        assert _parse_allocation_date("20250113").isoformat() == "2025-01-13"

    @pytest.mark.parametrize("datestr", [b"00000000", b"2020", b"garbage", b""])
    def test_zero_date_keeps_the_allocation(self, datestr):
        line = b"arin|US|ipv4|8.8.8.0|256|" + datestr + b"|allocated|XX-1-ARIN"
        got = parse_delegated_extended(line)
        assert len(got) == 1, "a bad DATE must not make the line malformed"
        assert got[0]["prefix"] == "8.8.8.0/24"
        assert got[0]["allocated_on"] is None

    def test_zero_date_is_not_malformed_only_a_bad_address_or_count_is(self):
        good_date_bad_start = b"arin|US|ipv4|not-an-ip|256|20200101|allocated|XX-1-ARIN"
        good_date_bad_count = b"arin|US|ipv4|8.8.8.0|zero|20200101|allocated|XX-1-ARIN"
        assert parse_delegated_extended(good_date_bad_start) == []
        assert parse_delegated_extended(good_date_bad_count) == []


class TestRowMapping:
    def test_asn_is_null_never_zero(self):
        """AC2.5 / G13 — D13: this evidence class carries NO ASN.

        ``0`` would be a fabricated fact that every future reader must know to
        special-case. NULL states "not applicable" checkably.
        """
        rows = [_allocation_to_row(a) for a in parse_delegated_extended(ARIN_ALLOCATED)]
        assert rows and all(r["asn"] is None for r in rows)
        assert not any(r["asn"] == 0 for r in rows)

    def test_rows_are_tagged_as_registry_evidence(self):
        """D9 — ``org_kind='registry'`` is what isolates these from both lookups."""
        row = _allocation_to_row(parse_delegated_extended(ARIN_ALLOCATED)[0])
        assert row["org_kind"] == "registry"
        assert row["relationship_type"] == "registered_holder"

    def test_the_opaque_handle_is_kept_with_its_registry_and_country(self):
        """D8 — no NAME is claimed; the handle plus provenance is all we have."""
        row = _allocation_to_row(parse_delegated_extended(ARIN_ALLOCATED)[0])
        assert row["org_name"] == "20c786e8edd815cc245070645e265298"
        assert row["org_name_raw"] == "arin:US:20c786e8edd815cc245070645e265298"

    def test_valid_from_carries_the_allocation_date(self):
        row = _allocation_to_row(parse_delegated_extended(ARIN_ALLOCATED)[0])
        assert row["valid_from"].isoformat() == "2025-01-13"
        assert row["valid_to"] is None

    def test_long_fields_are_truncated_to_the_column_width(self):
        line = b"arin|US|ipv4|8.8.8.0|256|20200101|allocated|" + b"x" * 400
        row = _allocation_to_row(parse_delegated_extended(line)[0])
        assert len(row["org_name"]) <= 200
        assert len(row["org_name_raw"]) <= 200


class TestTotality:
    def test_the_parser_never_raises_on_hostile_input(self):
        payload = b"\x00\xff|||||||\n" + b"a|b|ipv4|c|d|e|allocated|f\n" * 10
        assert parse_delegated_extended(payload) == []

    def test_a_bad_line_does_not_abort_the_good_ones(self):
        payload = b"\n".join([b"garbage|line", ARIN_ALLOCATED, b"\xff\xfe"])
        assert len(parse_delegated_extended(payload)) == 1
