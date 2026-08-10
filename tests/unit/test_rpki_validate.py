"""RFC 6811 route-origin validation (AC3.1). Pure — no Postgres, no network.

The three-state result is what these tests protect. Collapsing ``notfound`` into
``invalid`` would down-rank the majority of the routing table, which is unsigned
and perfectly legitimate; collapsing it the other way would erase the one signal
that identifies a genuinely disputed announcement.
"""

import pytest

from apps.api.services.rpki_validate import Roa, validate_origin

pytestmark = pytest.mark.unit


def _roa(prefix: str, asn: int, max_length: int) -> Roa:
    return Roa(prefix=prefix, asn=asn, max_length=max_length)


# Shape taken from the live Cloudflare dump
# (https://rpki.cloudflare.com/rpki.json, fetched 2026-08-07):
#   {"asn": 13335, "prefix": "1.0.0.0/24", "maxLength": 24, "ta": "apnic", …}
_CLOUDFLARE = _roa("1.0.0.0/24", 13335, 24)


class TestRfc6811Verdicts:
    @pytest.mark.parametrize(
        "prefix,asn,roas,expected",
        [
            # Exact match: same prefix, same AS, length within maxLength.
            ("1.0.0.0/24", 13335, [_CLOUDFLARE], "valid"),
            # More specific but still inside maxLength.
            ("10.0.1.0/24", 64500, [_roa("10.0.0.0/16", 64500, 24)], "valid"),
            # More specific than maxLength allows — the subtle case. A matching
            # ASN is necessary but NOT sufficient.
            ("10.0.1.0/24", 64500, [_roa("10.0.0.0/16", 64500, 16)], "invalid"),
            # Covering ROA exists, wrong origin AS.
            ("10.0.0.0/16", 64501, [_roa("10.0.0.0/16", 64500, 24)], "invalid"),
            # Nothing covers it: unsigned space, which is neutral.
            ("203.0.113.0/24", 64500, [_roa("10.0.0.0/16", 64500, 24)], "notfound"),
            # No ROAs at all.
            ("203.0.113.0/24", 64500, [], "notfound"),
        ],
    )
    def test_the_verdict_matches_rfc_6811(self, prefix, asn, roas, expected):
        assert validate_origin(prefix, asn, roas) == expected

    def test_one_authorizing_roa_among_several_wins(self):
        """VALID is existential: ANY covering ROA authorizing the origin suffices.

        Multi-homed space legitimately carries one ROA per origin AS, so scanning
        to the first non-matching ROA and returning invalid would mark normal
        multi-homing as disputed.
        """
        roas = [
            _roa("10.0.0.0/16", 64501, 24),
            _roa("10.0.0.0/16", 64500, 24),
        ]
        assert validate_origin("10.0.1.0/24", 64500, roas) == "valid"


class TestTotality:
    """Never raises — this runs inside the resolver path."""

    @pytest.mark.parametrize(
        "prefix", ["", "not-a-prefix", "999.999.999.999/24", "10.0.0.0/99"]
    )
    def test_a_malformed_prefix_degrades_to_notfound(self, prefix):
        assert validate_origin(prefix, 64500, [_CLOUDFLARE]) == "notfound"

    def test_a_malformed_roa_is_ignored_not_trusted(self):
        bad = {"prefix": "garbage", "asn": "x", "max_length": None}
        assert validate_origin("1.0.0.0/24", 13335, [bad, _CLOUDFLARE]) == "valid"

    def test_a_null_asn_over_covered_space_is_invalid_not_valid(self):
        """A NULL-asn row can never satisfy a ROA, and must not be read as valid."""
        assert validate_origin("1.0.0.0/24", None, [_CLOUDFLARE]) == "invalid"

    def test_a_non_covering_roa_passed_in_by_a_sloppy_caller_is_ignored(self):
        """Degrade to notfound rather than to a wrong verdict."""
        assert validate_origin("203.0.113.0/24", 13335, [_CLOUDFLARE]) == "notfound"
