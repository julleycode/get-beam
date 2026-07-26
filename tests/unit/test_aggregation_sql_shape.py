"""Unit gates for the aggregation SQL + incremental merge semantics (Phase 3 / W1).

These are the pure-logic half of the Phase 3 contract. Everything that needs a
real Postgres (parity, idempotency, boundary, descoped-column behaviour) is
Docker-gated integration by construction — ``aggregate_visitors_for_site`` is raw
Postgres SQL (LAG, ARRAY_AGG ... FILTER, BOOL_OR, on_conflict_do_update), which
is why no unit-tier parity file may exist (plan Tier note, supplement cycle 1).

What IS assertable without a database:

* **E4** — with ``since=None`` the emitted SQL is BYTE-IDENTICAL to the
  pre-change query. The expected value below is frozen verbatim; the incremental
  path may only ever APPEND to it, never rewrite it.
* **E13** — the exact ``ai_source`` CASE expression (a symmetric COALESCE is
  wrong and would produce false "Arrived via ChatGPT" badges).
* **E14** — ``ip_address`` keeps its keep-if-set semantic.
* **D7** — ``avg_time_on_page`` and ``intent_score`` are absent from the
  incremental merge set entirely.
"""

import pytest

from apps.api.services import visitor_aggregator as va

pytestmark = pytest.mark.unit


EXPECTED_FULL_RECOMPUTE_SQL = """
        WITH session_boundaries AS (
            SELECT
                visitor_id, created_at, event_type, url, referrer,
                utm_source, utm_medium, country_code, device_type,
                scroll_depth, time_on_page, ip_address, optout, is_flagged_abuse,
                CASE
                    WHEN created_at - LAG(created_at) OVER (
                        PARTITION BY visitor_id ORDER BY created_at
                    ) > INTERVAL '30 minutes' THEN 1
                    ELSE 0
                END AS is_new_session
            FROM events
            WHERE site_id = :site_id
        ),
        session_numbered AS (
            SELECT *,
                SUM(is_new_session) OVER (
                    PARTITION BY visitor_id ORDER BY created_at
                ) + 1 AS session_num
            FROM session_boundaries
        )
        SELECT
            visitor_id,
            MIN(created_at) FILTER (WHERE NOT is_flagged_abuse) AS first_seen,
            MAX(created_at) FILTER (WHERE NOT is_flagged_abuse) AS last_seen,
            COUNT(*) FILTER (WHERE event_type = 'pageview' AND NOT is_flagged_abuse) AS total_pageviews,
            MAX(session_num) FILTER (WHERE NOT is_flagged_abuse) AS total_sessions,
            COALESCE(MAX(scroll_depth) FILTER (WHERE NOT is_flagged_abuse), 0) AS max_scroll_depth,
            COALESCE(AVG(time_on_page) FILTER (WHERE time_on_page > 0 AND NOT is_flagged_abuse), 0) AS avg_time_on_page,
            ARRAY_AGG(DISTINCT url) FILTER (WHERE event_type = 'pageview' AND url != '' AND NOT is_flagged_abuse) AS pages_visited,
            MAX(referrer) FILTER (WHERE referrer != '' AND NOT is_flagged_abuse) AS top_referrer,
            (ARRAY_AGG(referrer ORDER BY created_at ASC) FILTER (WHERE event_type = 'pageview' AND NOT is_flagged_abuse))[1] AS first_touch_referrer,
            MAX(utm_source) FILTER (WHERE utm_source != '' AND NOT is_flagged_abuse) AS utm_source,
            MAX(utm_medium) FILTER (WHERE utm_medium != '' AND NOT is_flagged_abuse) AS utm_medium,
            MAX(country_code) FILTER (WHERE country_code != '' AND NOT is_flagged_abuse) AS country_code,
            MAX(device_type) FILTER (WHERE device_type != '' AND NOT is_flagged_abuse) AS device_type,
            (ARRAY_AGG(ip_address ORDER BY created_at DESC) FILTER (WHERE ip_address != '' AND NOT is_flagged_abuse))[1] AS latest_ip,
            BOOL_OR(optout) AS do_not_resolve,
            BOOL_OR(is_flagged_abuse) AS abuse_flagged
        FROM session_numbered
        GROUP BY visitor_id
    """


class TestE4ByteIdenticalUnderSinceNone:
    def test_since_none_sql_is_byte_identical_to_the_frozen_query(self):
        assert va.build_aggregate_sql(None) == EXPECTED_FULL_RECOMPUTE_SQL

    def test_incremental_sql_only_appends_to_the_frozen_query(self):
        """Every frozen line must survive verbatim in the incremental variant."""
        import datetime

        incremental = va.build_aggregate_sql(datetime.datetime(2026, 1, 1))
        for line in EXPECTED_FULL_RECOMPUTE_SQL.splitlines():
            if "total_sessions" in line or "WHERE site_id" in line:
                continue  # the two documented insertion points
            assert line in incremental, line


class TestIncrementalWindowMath:
    def test_read_window_starts_30_minutes_before_the_watermark(self):
        """LAG must see one event before the window to classify the first row."""
        from datetime import timedelta

        assert va.BOUNDARY_LOOKBACK == timedelta(minutes=30)

    def test_incremental_reads_from_lookback_but_merges_only_after_since(self):
        import datetime

        sql = va.build_aggregate_sql(datetime.datetime(2026, 1, 1))
        assert "AND created_at > :lookback_start" in sql
        assert "WHERE created_at > :since" in sql

    def test_incremental_sessions_expression_is_a_delta_not_a_max(self):
        """A window-local MAX(session_num) restarts at 1 and would under-count."""
        import datetime

        sql = va.build_aggregate_sql(datetime.datetime(2026, 1, 1))
        assert "MAX(session_num) FILTER" not in sql
        assert "is_new_session = 1 OR is_first_in_window = 1" in sql

    def test_full_recompute_keeps_the_max_session_expression(self):
        assert "MAX(session_num) FILTER" in va.build_aggregate_sql(None)
        assert "is_first_in_window" not in va.build_aggregate_sql(None)


def _expr(column: str) -> str:
    return str(va._INCREMENTAL_SET[column])


class TestMergeSemantics:
    def test_e13_ai_source_uses_the_exact_conditional_case_expression(self):
        expected = (
            "CASE WHEN NULLIF(visitors.first_touch_referrer, '') IS NOT NULL "
            "THEN visitors.ai_source ELSE EXCLUDED.ai_source END"
        )
        assert _expr("ai_source") == expected

    def test_e13_ai_source_is_never_a_bare_symmetric_coalesce(self):
        """classify_ai_source returns NULL for every ordinary referrer, so a
        symmetric COALESCE would stamp an AI label onto a kept google.com touch."""
        assert "COALESCE(NULLIF(visitors.ai_source" not in _expr("ai_source")

    def test_d6_first_touch_referrer_is_keep_existing_if_set(self):
        assert _expr("first_touch_referrer") == (
            "COALESCE(NULLIF(visitors.first_touch_referrer, ''), EXCLUDED.first_touch_referrer)"
        )

    def test_e14_ip_address_keeps_a_stored_value_when_the_window_has_none(self):
        assert _expr("ip_address") == "COALESCE(EXCLUDED.ip_address, visitors.ip_address)"

    @pytest.mark.parametrize("column", ["total_pageviews", "total_sessions"])
    def test_counters_are_additive_not_set(self, column):
        assert _expr(column) == f"visitors.{column} + EXCLUDED.{column}"

    def test_pages_visited_is_a_union_not_a_replacement(self):
        expr = _expr("pages_visited")
        assert "jsonb_agg(DISTINCT p)" in expr
        assert "visitors.pages_visited" in expr and "EXCLUDED.pages_visited" in expr

    @pytest.mark.parametrize("column", ["do_not_resolve", "is_abuse_flagged"])
    def test_sticky_flags_stay_sticky(self, column):
        assert _expr(column) == f"visitors.{column} OR EXCLUDED.{column}"

    def test_max_scroll_depth_is_merged_with_greatest(self):
        assert _expr("max_scroll_depth") == (
            "GREATEST(visitors.max_scroll_depth, EXCLUDED.max_scroll_depth)"
        )


class TestD7DescopedColumns:
    @pytest.mark.parametrize("column", ["avg_time_on_page", "intent_score"])
    def test_descoped_columns_are_absent_from_the_incremental_merge_set(self, column):
        """A window-only value for either would be WRONG, not merely stale.
        The full-recompute repair sweep is their sole writer."""
        assert column not in va._INCREMENTAL_SET

    def test_full_recompute_path_still_writes_both(self):
        import inspect

        src = inspect.getsource(va._upsert_visitor)
        assert '"avg_time_on_page": avg_time_on_page' in src
        assert '"intent_score": intent' in src


class TestSignatureCompatibility:
    def test_since_is_an_optional_third_argument(self):
        """E3 — 2 production callers and ~15 test call sites pass 2 args."""
        import inspect

        sig = inspect.signature(va.aggregate_visitors_for_site)
        assert list(sig.parameters) == ["db", "site_id", "since"]
        assert sig.parameters["since"].default is None
