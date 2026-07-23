"""Handoff Detection H2 — fetch↔click correlation unit tests (Docker-free).

Drives the pure ``correlate_fetch_to_clicks`` / ``_compute_confidence`` helpers with
synthetic pageview-shaped objects and a deterministic clock. Proves:
- AC-H2-1: a link is created for a same-family click inside the 30-min window.
- AC-H2-2: no link outside the window / on vendor mismatch.
- Confidence formula: high/medium tiers, Perplexity cap, no-low-writes policy.
- AC-H2-5: no cross-site linking regardless of timing.
- Tie-break: exact page wins over smaller delta; then smallest delta.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from apps.api.services.agent_handoff_correlation import (
    _WINDOW_SECONDS,
    _compute_confidence,
    correlate_fetch_to_clicks,
)

pytestmark = pytest.mark.unit

_T0 = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)


def _click(
    *,
    site_id="site-1",
    visitor_id="vid-1",
    page_path="/pricing",
    referrer="https://chatgpt.com/",
    after_seconds=60,
):
    """A synthetic same-site pageview click ``after_seconds`` after the fetch."""
    return SimpleNamespace(
        site_id=site_id,
        visitor_id=visitor_id,
        page_path=page_path,
        referrer=referrer,
        created_at=_T0 + timedelta(seconds=after_seconds),
    )


def _correlate(fetch_page_path="/pricing", fetch_vendor="openai", **kw):
    return correlate_fetch_to_clicks(
        fetch_site_id="site-1",
        fetch_vendor=fetch_vendor,
        fetch_page_path=fetch_page_path,
        fetch_at=_T0,
        **kw,
    )


# --- AC-H2-1: link created within window -----------------------------------


def test_link_created_within_window():
    match = _correlate(candidate_events=[_click(after_seconds=120)])
    assert match is not None
    assert match["visitor_id"] == "vid-1"
    assert match["confidence"] == "high"  # exact page + delta 120s <= 300
    assert match["delta_seconds"] == 120
    assert match["matched_page"] == "/pricing"


# --- AC-H2-2: no link outside window / vendor mismatch ----------------------


def test_no_link_outside_window():
    # 31 minutes later = 1860s > 1800s window → no candidate.
    match = _correlate(candidate_events=[_click(after_seconds=1860)])
    assert match is None


def test_no_link_before_fetch():
    # A click BEFORE the fetch (negative delta) can't be a handoff.
    match = _correlate(candidate_events=[_click(after_seconds=-30)])
    assert match is None


def test_no_link_vendor_mismatch():
    # Fetch vendor openai (→ chatgpt) but the click came via perplexity.ai.
    match = _correlate(
        candidate_events=[_click(referrer="https://perplexity.ai/")]
    )
    assert match is None


def test_no_link_non_ai_referrer():
    # Ordinary organic/direct referrer never correlates.
    match = _correlate(
        candidate_events=[_click(referrer="https://google.com/search?q=x")]
    )
    assert match is None


def test_unmapped_fetch_vendor_short_circuits():
    # bytespider has no family mapping (and is structurally never on-demand) →
    # .get() returns None → no candidate match, no raise.
    match = _correlate(
        fetch_vendor="bytespider", candidate_events=[_click()]
    )
    assert match is None


# --- Confidence formula (LOCKED Decisions 3-4) ------------------------------


def test_confidence_high_exact_page_fast():
    match = _correlate(candidate_events=[_click(after_seconds=200)])
    assert match["confidence"] == "high"


def test_confidence_medium_slow_delta():
    # Exact page but delta 600s (>300, <=1800) → medium.
    match = _correlate(candidate_events=[_click(after_seconds=600)])
    assert match["confidence"] == "medium"


def test_confidence_medium_page_mismatch():
    # Fast delta but the agent fetched a different page than the human landed on.
    match = _correlate(
        candidate_events=[_click(page_path="/other", after_seconds=60)]
    )
    assert match is not None
    assert match["confidence"] == "medium"
    # matched_page is always the FETCH page, not the click page.
    assert match["matched_page"] == "/pricing"


def test_perplexity_capped_medium():
    # Perplexity fetch, exact page, fast delta → would be high, but capped medium.
    match = correlate_fetch_to_clicks(
        fetch_site_id="site-1",
        fetch_vendor="perplexity",
        fetch_page_path="/pricing",
        fetch_at=_T0,
        candidate_events=[_click(referrer="https://perplexity.ai/", after_seconds=30)],
    )
    assert match is not None
    assert match["confidence"] == "medium"


def test_low_confidence_discarded_not_written():
    # A delta beyond the window computes as low → the pure formula returns None
    # (discard), never a writable tier. This is the no-low-writes policy.
    assert _compute_confidence(vendor="openai", exact_page=True, delta_seconds=2000) is None
    assert _compute_confidence(vendor="openai", exact_page=False, delta_seconds=5000) is None
    # And a negative delta (click before fetch) is also discarded.
    assert _compute_confidence(vendor="openai", exact_page=True, delta_seconds=-1) is None
    # Sanity: within-window always yields a writable tier (never low/None).
    assert _compute_confidence(vendor="openai", exact_page=True, delta_seconds=0) == "high"
    assert _compute_confidence(vendor="openai", exact_page=False, delta_seconds=_WINDOW_SECONDS) == "medium"


def test_page_path_none_falls_to_medium():
    # Fetch page_path None → exact match impossible → medium, matched_page None.
    match = _correlate(
        fetch_page_path=None, candidate_events=[_click(after_seconds=30)]
    )
    assert match is not None
    assert match["confidence"] == "medium"
    assert match["matched_page"] is None


# --- Tie-break (LOCKED Decision 5) ------------------------------------------


def test_tiebreak_exact_page_beats_smaller_delta():
    # A mismatched page at 10s vs an exact page at 120s → exact page wins.
    exact = _click(page_path="/pricing", visitor_id="exact", after_seconds=120)
    mismatch = _click(page_path="/other", visitor_id="mismatch", after_seconds=10)
    match = _correlate(candidate_events=[mismatch, exact])
    assert match["visitor_id"] == "exact"
    assert match["confidence"] == "high"


def test_tiebreak_smallest_delta_among_exact():
    near = _click(visitor_id="near", after_seconds=60)
    far = _click(visitor_id="far", after_seconds=200)
    match = _correlate(candidate_events=[far, near])
    assert match["visitor_id"] == "near"


# --- AC-H2-5: no cross-site linking -----------------------------------------


def test_no_cross_site_link():
    # A perfect same-page, fast, same-vendor click — but on a DIFFERENT site.
    foreign = _click(site_id="site-OTHER", after_seconds=30)
    match = _correlate(candidate_events=[foreign])
    assert match is None


def test_cross_site_click_excluded_but_same_site_kept():
    foreign = _click(site_id="site-OTHER", visitor_id="foreign", after_seconds=10)
    local = _click(site_id="site-1", visitor_id="local", after_seconds=90)
    match = _correlate(candidate_events=[foreign, local])
    assert match is not None
    assert match["visitor_id"] == "local"
