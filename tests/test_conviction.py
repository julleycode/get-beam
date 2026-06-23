"""Unit tests for the conviction "why this person" line (pure — no DB)."""

from apps.api.services.conviction import build_conviction


def test_enriched_with_hot_page_and_returns() -> None:
    line = build_conviction(
        {
            "job_title": "Head of Growth",
            "company_name": "Acme",
            "total_sessions": 3,
            "pages_visited": ["/", "/features", "/pricing"],
            "intent_score": 78,
        }
    )
    assert line == "Head of Growth at Acme · returned 3× · viewed your pricing page · intent 78"


def test_behavioural_only_no_enrichment() -> None:
    # Anonymous visitor (no job/company) still gets a story from behaviour.
    line = build_conviction(
        {
            "total_sessions": 2,
            "pages_visited": ["/a", "/b", "/c", "/d"],
            "max_scroll_depth": 90,
            "intent_score": 55,
        }
    )
    assert line == "returned 2× · viewed 4 pages · read deeply · intent 55"


def test_hot_page_beats_page_count() -> None:
    line = build_conviction(
        {"pages_visited": ["/", "/demo", "/x", "/y"], "intent_score": 60}
    )
    assert "viewed your demo page" in line
    assert "viewed 4 pages" not in line


def test_low_signal_returns_none() -> None:
    # One pageview, single session, low intent → nothing worth saying.
    assert (
        build_conviction(
            {"total_sessions": 1, "pages_visited": ["/"], "intent_score": 10}
        )
        is None
    )


def test_high_intent_alone_still_speaks() -> None:
    # No behavioural parts but intent >= 40 → at least surface the score.
    assert build_conviction({"intent_score": 45}) == "intent 45"


def test_caps_to_three_signals_plus_score() -> None:
    line = build_conviction(
        {
            "job_title": "CTO",
            "company_name": "Beta",
            "total_sessions": 4,
            "pages_visited": ["/pricing"],
            "max_scroll_depth": 80,
            "intent_score": 99,
        }
    )
    # 3 behavioural signals max, then the score — depth gets dropped.
    assert line == "CTO at Beta · returned 4× · viewed your pricing page · intent 99"
    assert "read deeply" not in line
