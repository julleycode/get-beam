"""Unit gates for the WS-B benchmark scripts' pure helpers (G7).

Covers the Q5 domain↔org matcher (bounded fuzzy tier, per-method labelling) and
the label_root helper (P1-2). No DB, no network — the prod-read and measurement
paths are operator/Hybrid gates run separately.
"""

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from build_ip_org_benchmark import (  # noqa: E402
    FREE_MAIL_EXCLUDE,
    expected_org_for,
    label_root,
)
from measure_ip_org_precision import match_org  # noqa: E402

pytestmark = pytest.mark.unit


class TestMatchOrg:
    def test_exact_match(self):
        assert match_org("acme", "acme") == (True, "exact")

    def test_token_subset_hit(self):
        # smaller {acme} ⊆ {acme, global}, and "acme" is length >= 4.
        assert match_org("acme", "acme global") == (True, "token_subset")

    def test_token_subset_near_miss_rejected(self):
        # No subset relation → no match.
        assert match_org("acme", "globex systems") == (False, None)

    def test_short_token_only_subset_rejected(self):
        # {ab} ⊆ {ab, global} but no token of length >= 4 in the smaller set.
        assert match_org("ab", "ab global") == (False, None)

    def test_none_prediction_is_no_match(self):
        assert match_org("acme", None) == (False, None)

    def test_empty_sides_are_no_match(self):
        assert match_org("", "acme") == (False, None)


class TestLabelRoot:
    @pytest.mark.parametrize(
        "domain,expected",
        [
            ("deloitte.co.uk", "deloitte"),
            ("acme.com", "acme"),
            ("mail.google.com", "google"),  # registrable google.com → google
            ("co.uk", None),  # bare public suffix
            ("", None),
        ],
    )
    def test_label_root(self, domain, expected):
        assert label_root(domain) == expected

    def test_expected_org_normalizes(self):
        # acme.com → label_root 'acme' → normalize_org_name → 'acme'
        assert expected_org_for("acme.com") == "acme"


class TestFreeMailExclude:
    def test_addendum_added_and_real_employers_removed(self):
        assert "gmail.com" in FREE_MAIL_EXCLUDE  # from _GENERIC_DOMAINS
        assert "live.com" in FREE_MAIL_EXCLUDE  # benchmark addendum
        assert "proton.me" in FREE_MAIL_EXCLUDE
        # real employers removed for the benchmark only
        assert "linkedin.com" not in FREE_MAIL_EXCLUDE
        assert "x.com" not in FREE_MAIL_EXCLUDE
