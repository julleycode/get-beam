"""AC-1: `normalize_category` is pure, deterministic, and never drops a value.

No flag precondition — the mapper is a pure function and is not gated.
"""

import pytest

from apps.api.services.campaign_benchmark import (
    BENCHMARK_CATEGORIES,
    normalize_category,
)

pytestmark = pytest.mark.unit


def test_unknown_input_maps_to_other_and_is_still_a_real_bucket():
    # "other" is a COUNTED bucket, not a discard — the k-floor is what protects
    # anonymity, not silent dropping.
    assert normalize_category("artisanal yak felting") == "other"
    assert "other" in BENCHMARK_CATEGORIES


@pytest.mark.parametrize("raw", [None, "", "   ", "\t\n"])
def test_missing_or_blank_maps_to_other(raw):
    assert normalize_category(raw) == "other"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("SaaS", "saas"),
        ("Software", "saas"),
        ("B2B Tech", "saas"),
        ("E-Commerce", "ecommerce"),
        ("ecommerce", "ecommerce"),
        ("Shopify store", "ecommerce"),
        ("DTC brand", "ecommerce"),
        ("Marketing agency", "agency"),
        ("Consulting", "agency"),
        ("Marketplace", "marketplace"),
        ("Fintech", "fintech"),
        ("Digital banking", "fintech"),
        ("Healthcare provider", "healthcare"),
        ("EdTech", "education"),
        ("Online publishing", "media"),
        ("Real Estate", "real_estate"),
        ("Travel booking", "travel"),
        ("Nonprofit", "nonprofit"),
    ],
)
def test_known_values_map_into_the_closed_vocabulary(raw, expected):
    assert normalize_category(raw) == expected


def test_output_is_always_inside_the_closed_vocabulary():
    samples = [
        None,
        "Software",
        "???",
        "REAL ESTATE",
        "travel",
        "unmapped nonsense 12345",
        "Shopify",
    ]
    for raw in samples:
        assert normalize_category(raw) in BENCHMARK_CATEGORIES


def test_case_and_whitespace_insensitive():
    assert (
        normalize_category("  SOFTWARE  ")
        == normalize_category("software")
        == normalize_category("Software")
        == "saas"
    )
    assert normalize_category("real_estate") == normalize_category("Real Estate")


def test_deterministic_across_repeated_calls():
    for raw in ("Software", "Widgets", None, "E-commerce"):
        assert len({normalize_category(raw) for _ in range(25)}) == 1


def test_pure_no_mutation_of_input():
    raw = "Software"
    normalize_category(raw)
    assert raw == "Software"


def test_more_specific_token_wins_over_generic_substring():
    # "real estate" contains no generic collision, but "e-commerce platform"
    # must not fall through to the "platform" -> saas token.
    assert normalize_category("E-commerce platform") == "ecommerce"
