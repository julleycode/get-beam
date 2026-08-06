"""Phase 4 D8 — regression test for the phantom-contact exclusion predicate.

The naive predicate the plan originally illustrated
(``~(is_imported_contact & (total_pageviews == 0))``) is SELF-CONTRADICTORY: a
phantom's own ``total_pageviews`` never changes after a merge (pageviews accrue
on the separate click-derived ``Visitor`` row that points AT the phantom via
``canonical_visitor_id``), so that form would exclude every merged phantom
FOREVER — the exact opposite of the design intent.

The correct predicate resolves the pointer with a correlated EXISTS subquery:

    NOT (is_imported_contact
         AND total_pageviews == 0
         AND NOT EXISTS (SELECT 1 FROM visitors v2
                         WHERE v2.canonical_visitor_id = visitors.visitor_id
                           AND v2.identity_status = 'merged'))

These are structural assertions over the compiled SQL — they fail loudly against
the naive form and pass only once the EXISTS pointer-resolution is present. The
end-to-end behavioural proof (real rows excluded / re-included against a live
Postgres) lives in ``tests/integration/test_contact_import.py`` and is a
documented environment known-gap in this sandbox (no Docker).
"""

import apps.api.main  # noqa: F401 — configures the SQLAlchemy mapper registry

from apps.api.services.agent_visitor_filters import human_only_visitor_filter


def _compiled(expr) -> str:
    return str(expr.compile(compile_kwargs={"literal_binds": True}))


def test_predicate_still_excludes_agent_derived_rows():
    # The pre-existing EvalLayer guarantee must survive the Phase 4 extension.
    assert "is_agent_derived" in _compiled(human_only_visitor_filter())


def test_predicate_excludes_unvisited_imported_contact():
    sql = _compiled(human_only_visitor_filter())
    assert "is_imported_contact" in sql
    assert "total_pageviews" in sql


def test_predicate_resolves_merged_pointer_via_exists_subquery():
    """A phantom with a merged child must stop being excluded.

    This is the assertion that fails against the naive ``total_pageviews``-only
    predicate: without a correlated EXISTS over ``canonical_visitor_id`` /
    ``identity_status = 'merged'`` there is no way for the predicate to ever
    observe that a real visit arrived.
    """
    sql = _compiled(human_only_visitor_filter())
    assert "EXISTS" in sql.upper()
    assert "canonical_visitor_id" in sql
    assert "merged" in sql


def test_predicate_is_not_a_permanent_imported_contact_exclusion():
    """Guards against a regression back to a blanket ``NOT is_imported_contact``."""
    sql = " ".join(_compiled(human_only_visitor_filter()).split())
    # A blanket exclusion would mention is_imported_contact with no pointer
    # resolution at all — the conjunction below is what makes it conditional.
    assert "total_pageviews" in sql and "EXISTS" in sql.upper()
