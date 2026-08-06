"""Phase 6 D1a — structural gate for the hot-imported-contacts query.

Two bugs this file exists to catch, both of which are SILENT in production (no
exception, no test failure, just a wrong customer-facing number or a dead route):

1. POINTER BYPASS. Reading ``last_seen`` off the PHANTOM imported-contact row
   instead of resolving the ``canonical_visitor_id`` pointer to its merged child.
   The phantom's own columns are frozen at import time, so that form reports
   every contact as permanently inactive.

2. MULTI-MERGED-CHILD DOUBLE-COUNT. A phantom can have 2+ merged children (same
   person, two devices, each pre-identification visitor_id merging onto the same
   email). A plain ``LEFT JOIN`` to those children fans out and counts one
   contact twice in "N". The query must resolve activity with a correlated
   scalar subquery (or GROUP BY), never an ungrouped join.

Structural assertions over the compiled SQL — no database. The row-level
arithmetic proof lives in ``tests/integration/test_hot_contacts.py`` and is a
documented Docker known-gap in this sandbox.
"""

import apps.api.main  # noqa: F401 — configures the SQLAlchemy mapper registry

from apps.api.services.hot_contacts import (
    DEFAULT_ACTIVITY_WINDOW_DAYS,
    hot_contacts_count_query,
    hot_contacts_list_query,
    imported_contacts_total_query,
)


def _sql(query) -> str:
    return str(query.compile(compile_kwargs={"literal_binds": True}))


def test_count_query_resolves_activity_through_canonical_pointer():
    """Activity comes from the merged CHILD, not the phantom's own last_seen."""
    sql = _sql(hot_contacts_count_query("site_x"))
    assert "canonical_visitor_id" in sql
    assert "merged" in sql
    assert "is_imported_contact" in sql
    assert "last_seen" in sql


def test_count_query_is_counting_safe_against_multi_merged_children():
    """A phantom with 2+ merged children must be counted exactly once.

    Enforced structurally: activity is aggregated with ``max(...)`` inside a
    correlated subquery, which yields one value per phantom and cannot fan out.
    A plain ungrouped LEFT JOIN over the child rows would have no ``max(`` and
    no correlated SELECT — this assertion fails against that form.
    """
    sql = _sql(hot_contacts_count_query("site_x")).lower()
    assert "max(" in sql, "activity must be aggregated per phantom, not joined row-wise"
    # A correlated subquery: an inner SELECT over visitors nested in the WHERE.
    assert sql.count("select") >= 2, "expected a correlated subquery, not a flat join"
    assert "group by" in sql or "max(" in sql


def test_count_query_counts_phantom_rows_not_joined_child_rows():
    """The COUNT target is the phantom's own id — never the child's."""
    sql = _sql(hot_contacts_count_query("site_x")).lower().replace(" ", "")
    assert "count(visitors.visitor_id)" in sql


def test_count_query_excludes_phantoms_with_no_merged_child():
    """Step B3: a phantom is active only through a merged child's activity.

    ``IS NOT NULL`` on the correlated activity value is what excludes a
    never-visited phantom; without it a NULL window comparison would still be
    filtered, but the intent must be explicit and stay explicit.
    """
    sql = _sql(hot_contacts_count_query("site_x")).upper()
    assert "IS NOT NULL" in sql


def test_count_query_is_site_scoped():
    """Cross-tenant isolation starts here: site_id is in the predicate."""
    assert "site_x" in _sql(hot_contacts_count_query("site_x"))


def test_total_query_has_no_activity_join():
    """The "of M" denominator counts every imported contact, active or not."""
    sql = _sql(imported_contacts_total_query("site_x"))
    assert "is_imported_contact" in sql
    assert "canonical_visitor_id" not in sql, "denominator must not filter on activity"
    assert "site_x" in sql


def test_list_query_returns_activity_timestamp_and_is_bounded():
    sql = _sql(hot_contacts_list_query("site_x")).lower()
    assert "activity_last_seen" in sql
    assert "max(" in sql, "list query must use the same counting-safe form"
    assert "limit" in sql
    assert "order by" in sql


def test_default_activity_window_is_one_week():
    assert DEFAULT_ACTIVITY_WINDOW_DAYS == 7


def test_hot_route_is_not_shadowed_by_visitor_id_route():
    """The literal /contacts/hot must be registered BEFORE /contacts/{visitor_id}.

    FastAPI matches in registration order. Reversed, every request to
    ``/contacts/hot`` resolves to ``get_imported_contact`` with
    ``visitor_id="hot"`` and 404s — a pure runtime bug with no import-time or
    type-level signal. This is the only automated guard on that ordering.
    """
    paths = [getattr(r, "path", "") for r in apps.api.main.app.routes]
    hot = "/api/v1/sites/{site_id}/contacts/hot"
    by_id = "/api/v1/sites/{site_id}/contacts/{visitor_id}"
    assert hot in paths, f"hot-contacts route not registered; got {[p for p in paths if 'contacts' in p]}"
    assert by_id in paths
    assert paths.index(hot) < paths.index(by_id), (
        "/contacts/hot is registered after /contacts/{visitor_id} and will be shadowed"
    )
