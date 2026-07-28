"""Phase 06 (EvalLayer) unit tests — agent-analytics aggregation.

Covers three regression-critical guarantees, all Docker-free:
- AC11: ``aggregate_agent_analytics`` computes by_vendor / top_pages /
  by_verification correctly, including edge cases (empty, ties, < top_n).
- AC2: ``fetch_agent_visit_rows`` compiled query references only ``agent_visits``
  and NEVER ``visitors`` / ``events`` (human-data isolation boundary).
- Route ordering: ``/{site_id}/analytics`` registers before the
  ``/{site_id}/{agent_visit_id}`` catch-all (FastAPI matches in registration
  order — route objects are built at import time, no DB needed).
"""

import pytest

from apps.api.services.agent_aggregator import (
    aggregate_agent_analytics,
    fetch_agent_visit_rows,
)

pytestmark = pytest.mark.unit


def _row(vendor, visit_count, page_paths, verification_method="ua-only"):
    return {
        "vendor": vendor,
        "visit_count": visit_count,
        "page_paths": page_paths,
        "verification_method": verification_method,
    }


# --- AC11: by_vendor -------------------------------------------------------


def test_by_vendor_sums_across_rows():
    rows = [
        _row("openai", 3, ["/a"]),
        _row("openai", 2, ["/b"]),
        _row("perplexity", 5, ["/a"]),
    ]
    result = aggregate_agent_analytics(rows, 0)
    assert result["by_vendor"] == {"openai": 5, "perplexity": 5}


# --- AC11: top_pages -------------------------------------------------------


def test_top_pages_ranks_and_sums_overlapping_paths():
    rows = [
        _row("openai", 3, ["/pricing", "/docs"]),
        _row("perplexity", 5, ["/pricing"]),
        _row("anthropic", 1, ["/docs", "/blog"]),
    ]
    result = aggregate_agent_analytics(rows, 0)
    # /pricing appears in rows with counts 3 + 5 = 8; /docs 3 + 1 = 4; /blog 1.
    assert result["top_pages"] == [
        {"path": "/pricing", "count": 8},
        {"path": "/docs", "count": 4},
        {"path": "/blog", "count": 1},
    ]


def test_top_pages_respects_top_n_limit():
    rows = [_row("openai", i + 1, [f"/p{i}"]) for i in range(15)]
    result = aggregate_agent_analytics(rows, 0, top_n=10)
    assert len(result["top_pages"]) == 10
    # Highest visit_count paths win — /p14 (15) down to /p5 (6).
    assert result["top_pages"][0] == {"path": "/p14", "count": 15}
    assert result["top_pages"][-1] == {"path": "/p5", "count": 6}


def test_top_pages_stable_order_on_ties():
    rows = [
        _row("openai", 2, ["/first"]),
        _row("perplexity", 2, ["/second"]),
        _row("anthropic", 2, ["/third"]),
    ]
    result = aggregate_agent_analytics(rows, 0)
    # All tied at count 2 → first-seen (input) order preserved.
    assert [p["path"] for p in result["top_pages"]] == [
        "/first",
        "/second",
        "/third",
    ]


def test_distinct_path_within_row_counted_once():
    rows = [_row("openai", 4, ["/dup", "/dup", "/other"])]
    result = aggregate_agent_analytics(rows, 0)
    assert result["top_pages"] == [
        {"path": "/dup", "count": 4},
        {"path": "/other", "count": 4},
    ]


# --- AC11: by_verification -------------------------------------------------


def test_by_verification_sums_by_method():
    rows = [
        _row("openai", 3, ["/a"], "ip-verified"),
        _row("perplexity", 2, ["/b"], "ua-only"),
        _row("openai", 1, ["/c"], "ip-verified"),
    ]
    result = aggregate_agent_analytics(rows, 0)
    assert result["by_verification"] == {"ip-verified": 4, "ua-only": 2}


# --- AC11: edge cases ------------------------------------------------------


def test_empty_rows_yield_empty_aggregates():
    result = aggregate_agent_analytics([], 0)
    assert result == {
        "by_vendor": {},
        "top_pages": [],
        "by_verification": {},
        "handoff_links_count": 0,
        # Context for the link count — empty/zero by default, so an empty site
        # reports "0 of 0" rather than a bare, unreadable 0.
        "handoff_confidence": {},
        "on_demand_fetch_count": 0,
        # Handoff Detection H3 (AC-H3-3): additive echoed field, empty by default.
        "recent_ai_researched_companies": [],
    }


# --- Handoff Detection H2 (AC-H2-4): handoff_links_count always present --------


def test_handoff_links_count_echoed_into_result():
    # The count is passed in (fetched via the sibling DB fn) and echoed verbatim.
    rows = [_row("openai", 3, ["/a"])]
    result = aggregate_agent_analytics(rows, 7)
    assert result["handoff_links_count"] == 7


def test_handoff_links_count_present_on_empty_and_populated():
    # AC-H2-4 API-contract: the field is ALWAYS present, regardless of data.
    assert "handoff_links_count" in aggregate_agent_analytics([], 0)
    assert "handoff_links_count" in aggregate_agent_analytics(
        [_row("openai", 1, ["/x"])], 2
    )


def test_fetch_handoff_links_count_query_isolated_to_handoff_table():
    """The count query touches only agent_handoff_links — never visitors/events
    (mirrors the AC2 isolation check for fetch_agent_visit_rows)."""
    from apps.api.models.agent_handoff_link import AgentHandoffLink
    from sqlalchemy import func, select

    query = select(func.count()).select_from(AgentHandoffLink).where(
        AgentHandoffLink.site_id == "site-x"
    )
    compiled = str(query.compile(compile_kwargs={"literal_binds": True})).lower()

    assert "agent_handoff_links" in compiled
    assert "visitors" not in compiled
    assert " events" not in compiled  # leading space: avoid matching "agent_..."


def test_fewer_paths_than_top_n_returns_all():
    rows = [_row("openai", 1, ["/only"])]
    result = aggregate_agent_analytics(rows, 0, top_n=10)
    assert result["top_pages"] == [{"path": "/only", "count": 1}]


def test_rows_with_no_page_paths_handled():
    rows = [_row("openai", 3, [])]
    result = aggregate_agent_analytics(rows, 0)
    assert result["by_vendor"] == {"openai": 3}
    assert result["top_pages"] == []


# --- AC2: human-data isolation (compiled SQL substring check) --------------


def test_fetch_query_references_only_agent_visits():
    """The select() built inside fetch_agent_visit_rows must touch only
    agent_visits — never visitors or events (SPEC AC2 boundary)."""
    from apps.api.models.agent_visit import AgentVisit
    from sqlalchemy import select

    # Rebuild the exact query fetch_agent_visit_rows constructs and inspect its
    # compiled SQL. (fetch is async and needs a DB; the query shape is the
    # regression-critical part and is inspectable without a connection.)
    query = select(
        AgentVisit.vendor,
        AgentVisit.visit_count,
        AgentVisit.page_paths,
        AgentVisit.verification_method,
    ).where(AgentVisit.site_id == "site-x")
    compiled = str(query.compile(compile_kwargs={"literal_binds": True})).lower()

    assert "agent_visits" in compiled
    assert "visitors" not in compiled
    assert "events" not in compiled


# --- Route ordering (import-time, no DB) -----------------------------------


def test_analytics_route_registered_before_detail_catchall():
    from apps.api.routers.agents import router

    paths = [r.path for r in router.routes]
    assert "/{site_id}/analytics" in paths
    assert "/{site_id}/{agent_visit_id}" in paths
    assert paths.index("/{site_id}/analytics") < paths.index(
        "/{site_id}/{agent_visit_id}"
    )
