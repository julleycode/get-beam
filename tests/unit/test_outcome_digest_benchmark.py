"""AC-8: the digest benchmark line.

`build_digest_email` stays PURE with a keyword-only defaulted argument;
`DigestStats` is unchanged; the digest stays PII-free and forwardable; the line
says "category average" and never "median"; and the rendered line carries the
MPP/image-blocking open-rate caveat — the digest is BUILT to be forwarded, so an
uncaveated open rate would travel outside the account.
"""

import inspect
import re

import pytest

from apps.api.services.campaign_stats import OPEN_RATE_CAVEAT
from apps.api.services.outcome_digest import (
    DigestBenchmark,
    DigestStats,
    build_digest_email,
)

pytestmark = pytest.mark.unit

_STATS = DigestStats(
    sent=40, clicked=6, conversions=3, attributed=2, attributed_revenue_cents=12500
)


def test_digest_stats_shape_is_unchanged():
    # DigestStats is a second public structure with its own producer; the
    # open-rate value rides in the benchmark argument instead.
    assert DigestStats._fields == (
        "sent",
        "clicked",
        "conversions",
        "attributed",
        "attributed_revenue_cents",
    )


def test_positional_signature_and_return_shape_unchanged():
    sig = inspect.signature(build_digest_email)
    params = list(sig.parameters.values())
    assert [p.name for p in params[:3]] == ["site_name", "stats", "visitors"]
    assert all(
        p.kind is not inspect.Parameter.KEYWORD_ONLY for p in params[:3]
    )
    benchmark = sig.parameters["benchmark"]
    assert benchmark.kind is inspect.Parameter.KEYWORD_ONLY
    assert benchmark.default is None
    subject, html = build_digest_email("Acme", _STATS)
    assert isinstance(subject, str) and isinstance(html, str)


def test_flag_off_shape_no_benchmark_renders_exactly_as_before():
    with_default = build_digest_email("Acme", _STATS)
    explicit_none = build_digest_email("Acme", _STATS, benchmark=None)
    assert with_default == explicit_none
    assert "How you compare" not in with_default[1]
    assert OPEN_RATE_CAVEAT not in with_default[1]


def test_benchmark_line_renders_the_category_average_with_the_mpp_caveat():
    _, html = build_digest_email(
        "Acme",
        _STATS,
        benchmark=DigestBenchmark(
            category_label="saas", site_open_rate=0.42, category_open_rate=0.31
        ),
    )
    assert "How you compare" in html
    assert "42.0%" in html
    assert "31.0%" in html
    assert "category average" in html
    # The caveat must ride the SAME email as the number.
    assert "Apple Mail Privacy Protection" in html
    assert "Clicks are the reliable signal" in html


def test_benchmark_line_never_says_median():
    _, html = build_digest_email(
        "Acme",
        _STATS,
        benchmark=DigestBenchmark("saas", 0.42, 0.31),
    )
    assert not re.search(r"\bmedian\b", html, re.I)


def test_no_sends_renders_no_data_never_zero_percent():
    _, html = build_digest_email(
        "Acme",
        DigestStats(0, 0, 0, 0, 0),
        benchmark=DigestBenchmark("saas", None, 0.31),
    )
    assert "no sends this week" in html
    assert "0.0%" not in html
    # The category average is still shown, still caveated.
    assert "31.0%" in html
    assert "Apple Mail Privacy Protection" in html


def test_measured_zero_is_rendered_as_zero_not_as_no_data():
    _, html = build_digest_email(
        "Acme", _STATS, benchmark=DigestBenchmark("saas", 0.0, 0.31)
    )
    assert "0.0%" in html
    assert "no sends this week" not in html


def test_missing_category_row_renders_nothing():
    _, html = build_digest_email(
        "Acme", _STATS, benchmark=DigestBenchmark("saas", 0.42, None)
    )
    assert "How you compare" not in html


def test_digest_benchmark_line_carries_no_pii_and_no_site_count():
    _, html = build_digest_email(
        "Acme",
        _STATS,
        benchmark=DigestBenchmark("real_estate", 0.42, 0.31),
    )
    # site_count is an anonymity parameter and must never be tenant-visible.
    assert "site_count" not in html
    assert "sites contributed" not in html
    assert "real estate" in html  # label is a closed-vocabulary token only


def test_build_digest_email_is_pure_no_db_no_settings_mutation():
    args = ("Acme", _STATS)
    kwargs = {"benchmark": DigestBenchmark("saas", 0.42, 0.31)}
    first = build_digest_email(*args, **kwargs)
    second = build_digest_email(*args, **kwargs)
    assert first == second


def test_no_period_over_period_delta_in_rendered_html():
    _, html = build_digest_email(
        "Acme", _STATS, benchmark=DigestBenchmark("saas", 0.42, 0.31)
    )
    for token in ("last week", "vs last", "previous period", "week over week"):
        assert token not in html.lower()
