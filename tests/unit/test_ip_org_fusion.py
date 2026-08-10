"""Confidence fusion and classification (AC4.1-AC4.4, AC4.2a). Pure, no DB.

Every arithmetic expectation below is written as ``base + signal`` rather than as
a bare literal, so a weight change shows up as a deliberate edit to the weight
constant instead of as a mystery number nobody can re-derive.
"""

import pytest

from apps.api.services import ip_org_fusion
from apps.api.services.ip_org_fusion import (
    BASE_ROUTE_ORIGIN,
    CONFIDENCE_CEILING,
    CONFIDENCE_FLOOR,
    W_ALLOCATION_EXACT,
    W_ALLOCATION_SUBDELEGATED,
    W_ALLOCATION_UNCOVERED,
    W_RPKI_INVALID,
    W_RPKI_VALID,
    derive_classification,
    fuse_org_hypothesis,
)

pytestmark = pytest.mark.unit


def _route(prefix: str = "10.1.2.0/24", asn: int = 64500) -> dict:
    return {
        "org_name": "acme widgets",
        "org_name_raw": "Acme Widgets, Inc.",
        "asn": asn,
        "org_kind": "org",
        "prefix": prefix,
    }


def _holder(prefix: str) -> dict:
    # No ``asn`` key AT ALL: registered_holder evidence carries none, and fusion
    # must never reach for one. A KeyError here would be the bug.
    return {"prefix": prefix, "org_name": "xx-1-arin", "org_name_raw": "arin:US:XX-1-ARIN"}


class TestPurity:
    def test_the_module_imports_no_database_or_network_at_module_scope(self):
        """AC4.1 — purity is what makes every weight row table-testable."""
        source = open(ip_org_fusion.__file__).read()
        for banned in (
            "import httpx",
            "from sqlalchemy",
            "import sqlalchemy",
            "async_session",
            "AsyncSession",
        ):
            assert banned not in source, f"fusion must stay pure; found {banned!r}"


class TestWeightTable:
    @pytest.mark.parametrize(
        "rir_rows,corpus,rpki,expected",
        [
            # Announced == covering allocation: the holder announces its own space.
            ([_holder("10.1.2.0/24")], True, "notfound", BASE_ROUTE_ORIGIN + W_ALLOCATION_EXACT),
            # 1-3 bits more specific — the neutral band, explicitly 0.00.
            ([_holder("10.1.0.0/22")], True, "notfound", BASE_ROUTE_ORIGIN),
            # >= 4 bits: plausibly a provider announcing a customer's space.
            ([_holder("10.0.0.0/16")], True, "notfound", BASE_ROUTE_ORIGIN + W_ALLOCATION_SUBDELEGATED),
            # Corpus loaded, nothing covers it — an evidenced anomaly.
            ([], True, "notfound", BASE_ROUTE_ORIGIN + W_ALLOCATION_UNCOVERED),
            # RPKI legs, measured against an exact allocation.
            ([_holder("10.1.2.0/24")], True, "valid",
             BASE_ROUTE_ORIGIN + W_ALLOCATION_EXACT + W_RPKI_VALID),
            ([_holder("10.1.2.0/24")], True, "invalid",
             BASE_ROUTE_ORIGIN + W_ALLOCATION_EXACT + W_RPKI_INVALID),
        ],
    )
    def test_each_signal_moves_confidence_by_its_stated_weight(
        self, rir_rows, corpus, rpki, expected
    ):
        got = fuse_org_hypothesis(_route(), rir_rows, rpki, corpus)
        assert got is not None
        assert got["confidence"] == pytest.approx(
            max(CONFIDENCE_FLOOR, min(CONFIDENCE_CEILING, expected))
        )

    def test_the_most_specific_covering_allocation_is_used_not_an_arbitrary_one(self):
        """A /8 and a /24 can both cover, and they say different things.

        Fed both, the /24 must win — otherwise an exact-match announcement would
        be scored as sub-delegated purely because a wider allocation also exists.
        """
        got = fuse_org_hypothesis(
            _route(), [_holder("10.0.0.0/8"), _holder("10.1.2.0/24")], "notfound", True
        )
        assert got is not None
        assert got["confidence"] == pytest.approx(BASE_ROUTE_ORIGIN + W_ALLOCATION_EXACT)

    def test_registered_holder_rows_are_never_read_for_an_asn(self):
        """D13 — that evidence class has no ASN; reaching for one would raise."""
        got = fuse_org_hypothesis(_route(), [_holder("10.1.2.0/24")], "valid", True)
        assert got is not None  # no KeyError


class TestNoEvidenceBaseline:
    """AC4.2 — absence of a corpus must not look like evidence against the hit."""

    def test_corpus_absent_scores_exact_phase_2_parity(self):
        got = fuse_org_hypothesis(_route(), [], "notfound", False)
        assert got is not None
        assert got["confidence"] == pytest.approx(0.45)
        assert got["classification"] == "unclassified"
        assert any("no RIR allocation corpus" in u for u in got["uncertainty"])

    def test_corpus_present_but_prefix_uncovered_scores_the_evidenced_penalty(self):
        got = fuse_org_hypothesis(_route(), [], "notfound", True)
        assert got is not None
        assert got["confidence"] == pytest.approx(0.40)
        assert got["classification"] == "unclassified"
        assert any("no allocation covers" in u for u in got["uncertainty"])

    def test_fusion_never_raises_confidence_above_phase_2_without_evidence(self):
        """The two baselines differ ONLY by an evidenced signal."""
        absent = fuse_org_hypothesis(_route(), [], "notfound", False)
        present = fuse_org_hypothesis(_route(), [], "notfound", True)
        assert absent["confidence"] > present["confidence"]


class TestClampBounds:
    """AC4.3 — the ceiling keeps the paid path (0.7) authoritative."""

    def test_the_best_possible_evidence_is_capped_at_the_ceiling(self):
        got = fuse_org_hypothesis(_route(), [_holder("10.1.2.0/24")], "valid", True)
        # 0.45 + 0.15 + 0.15 = 0.75, clamped.
        assert got["confidence"] == CONFIDENCE_CEILING

    def test_the_worst_possible_evidence_never_drops_below_the_floor(self):
        got = fuse_org_hypothesis(_route(), [_holder("10.0.0.0/8")], "invalid", True)
        assert got["confidence"] >= CONFIDENCE_FLOOR

    @pytest.mark.parametrize("rpki", ["valid", "invalid", "notfound"])
    @pytest.mark.parametrize("corpus", [True, False])
    @pytest.mark.parametrize(
        "rir", [[], [_holder("10.1.2.0/24")], [_holder("10.0.0.0/8")]]
    )
    def test_confidence_stays_inside_the_clamp_for_every_combination(
        self, rpki, corpus, rir
    ):
        got = fuse_org_hypothesis(_route(), rir, rpki, corpus)
        assert CONFIDENCE_FLOOR <= got["confidence"] <= CONFIDENCE_CEILING


class TestEvidenceAndUncertainty:
    """AC4.4 — the score must always be able to explain itself."""

    @pytest.mark.parametrize("rpki", ["valid", "invalid", "notfound"])
    @pytest.mark.parametrize("corpus", [True, False])
    def test_every_hypothesis_carries_at_least_one_evidence_string(self, rpki, corpus):
        got = fuse_org_hypothesis(_route(), [_holder("10.1.2.0/24")], rpki, corpus)
        assert got["evidence"], "a hypothesis with no stated evidence is not honest"

    @pytest.mark.parametrize(
        "rir,corpus,rpki",
        [
            ([], False, "notfound"),
            ([], True, "notfound"),
            ([_holder("10.0.0.0/8")], True, "notfound"),
            ([_holder("10.1.2.0/24")], True, "invalid"),
        ],
    )
    def test_a_low_confidence_hypothesis_always_states_why(self, rir, corpus, rpki):
        got = fuse_org_hypothesis(_route(), rir, rpki, corpus)
        assert got["confidence"] < 0.5
        assert got["uncertainty"], "below 0.5 the gaps must be named"


class TestNoSubject:
    def test_a_prefix_with_no_route_origin_row_yields_no_hypothesis(self):
        """Registry evidence alone is corroboration, never the subject."""
        assert fuse_org_hypothesis(None, [_holder("10.0.0.0/8")], "valid", True) is None

    def test_a_route_row_without_an_organization_yields_no_hypothesis(self):
        assert fuse_org_hypothesis({**_route(), "org_name": ""}, [], "valid", True) is None


class TestClassification:
    """AC4.2a — total and deterministic under FIRST-MATCH ordering."""

    VOCABULARY = {
        "disputed_origin",
        "likely_operational_customer",
        "registered_operator",
        "unclassified",
    }

    @pytest.mark.parametrize(
        "row,kwargs,expected",
        [
            # Row 1 — RPKI invalid, and it wins even though rows 2-5 also match.
            (1, dict(rpki_state="invalid", rir_corpus_present=True, covered=True, delta=0),
             "disputed_origin"),
            # Row 2 — >= 4 bits more specific.
            (2, dict(rpki_state="notfound", rir_corpus_present=True, covered=True, delta=8),
             "likely_operational_customer"),
            # Row 3 — exactly the covering allocation.
            (3, dict(rpki_state="notfound", rir_corpus_present=True, covered=True, delta=0),
             "registered_operator"),
            # Row 4 — the 1-3 bit neutral band.
            (4, dict(rpki_state="notfound", rir_corpus_present=True, covered=True, delta=2),
             "likely_operational_customer"),
            # Row 5a — no corpus loaded.
            (5, dict(rpki_state="notfound", rir_corpus_present=False, covered=False, delta=None),
             "unclassified"),
            # Row 5b — corpus loaded but uncovered.
            (5, dict(rpki_state="valid", rir_corpus_present=True, covered=False, delta=None),
             "unclassified"),
        ],
    )
    def test_every_d12_row_returns_its_stated_value(self, row, kwargs, expected):
        assert derive_classification(**kwargs) == expected, f"D12 row {row}"

    def test_row_1_deliberately_overlaps_rows_2_to_5_and_still_wins(self):
        """Overlap is the DESIGN, and first-match is what makes it total.

        An RPKI-invalid prefix necessarily also has an allocation state, so the
        rows cannot be a partition. Asserting mutual exclusivity across all five
        would fail on a legitimate input; the real claim is about SELECTION.
        """
        for delta in (0, 2, 8):
            assert (
                derive_classification(
                    rpki_state="invalid",
                    rir_corpus_present=True,
                    covered=True,
                    delta=delta,
                )
                == "disputed_origin"
            )

    def test_rows_2_to_5_partition_the_allocation_space(self):
        """The narrower claim that DOES hold: exclusive and exhaustive among themselves."""
        seen = set()
        for delta in (-4, 0, 1, 3, 4, 16):
            seen.add(
                derive_classification(
                    rpki_state="notfound", rir_corpus_present=True, covered=True, delta=delta
                )
            )
        assert seen == {"registered_operator", "likely_operational_customer"}

    @pytest.mark.parametrize("rpki", ["valid", "invalid", "notfound", "", "nonsense"])
    @pytest.mark.parametrize("corpus", [True, False])
    @pytest.mark.parametrize("covered", [True, False])
    @pytest.mark.parametrize("delta", [None, -1, 0, 1, 3, 4, 24])
    def test_the_function_is_total_and_stays_inside_the_vocabulary(
        self, rpki, corpus, covered, delta
    ):
        got = derive_classification(
            rpki_state=rpki, rir_corpus_present=corpus, covered=covered, delta=delta
        )
        assert got in self.VOCABULARY
        # The two values deleted as unreachable by construction must never return.
        assert got not in ("registry_only", "likely_infrastructure")


class TestCorpusProbeCache:
    """The TTL is the real staleness bound; invalidation is a local optimization."""

    def setup_method(self):
        ip_org_fusion.invalidate_rir_corpus_cache()

    def teardown_method(self):
        ip_org_fusion.invalidate_rir_corpus_cache()

    def test_a_cold_cache_reports_no_value(self):
        assert ip_org_fusion.get_cached_rir_corpus_present() is None

    def test_a_set_value_is_returned_until_invalidated(self):
        ip_org_fusion.set_cached_rir_corpus_present(True)
        assert ip_org_fusion.get_cached_rir_corpus_present() is True
        ip_org_fusion.invalidate_rir_corpus_cache()
        assert ip_org_fusion.get_cached_rir_corpus_present() is None

    def test_an_expired_entry_reports_cold_rather_than_stale(self, monkeypatch):
        ip_org_fusion.set_cached_rir_corpus_present(True)
        real = ip_org_fusion.time.monotonic
        monkeypatch.setattr(
            ip_org_fusion.time, "monotonic", lambda: real() + 301.0
        )
        assert ip_org_fusion.get_cached_rir_corpus_present() is None

    def test_false_is_cached_as_a_real_value_not_as_a_miss(self):
        """A cached False must not be indistinguishable from a cold cache."""
        ip_org_fusion.set_cached_rir_corpus_present(False)
        assert ip_org_fusion.get_cached_rir_corpus_present() is False
