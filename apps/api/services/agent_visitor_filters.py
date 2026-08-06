"""Shared human-only visitor predicate (EvalLayer Phase 05, GUARD #2 / SPEC AC2).

Agent-company-resolution creates synthetic ``Visitor`` rows (``is_agent_derived
= True``) so an agent visit's IP can run through the existing identity-resolution
waterfall. Those rows must NEVER appear in any human-facing surface — visitor
lists, stats, resolution eligibility, segmentation, or aggregation.

Every human-data query site imports and calls ``human_only_visitor_filter()``
instead of hand-copying ``Visitor.is_agent_derived.is_(False)``. A single choke
point means a future change to the exclusion semantics (e.g. a second condition)
touches exactly one place.

Identity-honesty Phase 4 added that second condition: a PHANTOM imported contact
that has not been visited yet. Unlike the agent-derived exclusion it is
CONDITIONAL — see the inline comment in ``human_only_visitor_filter``.
"""


def human_only_visitor_filter():
    """SQLAlchemy predicate excluding agent-derived synthetic Visitor rows.

    Use at every human-data query site::

        from apps.api.services.agent_visitor_filters import human_only_visitor_filter
        select(Visitor).where(..., human_only_visitor_filter())
    """
    from sqlalchemy import and_, literal_column, not_, select
    from sqlalchemy.orm import aliased

    from apps.api.models.visitor import Visitor

    # Identity-honesty Phase 4: a PHANTOM imported contact (is_imported_contact,
    # created by the CSV import with no real traffic) is excluded ONLY while it
    # has not been visited yet.
    #
    # "Has been visited" CANNOT be read off the phantom's own total_pageviews —
    # that column never changes after a merge. When a real visit later resolves
    # to the same email, _save_identified's email-dedup branch marks the
    # CLICK-DERIVED row "merged" and points its canonical_visitor_id AT the
    # phantom; the phantom itself is untouched. So the pointer must be resolved
    # with a correlated EXISTS over that child row — a total_pageviews-only test
    # would exclude every merged phantom permanently, the exact opposite of the
    # intent.
    merged_child = aliased(Visitor)
    has_merged_child = (
        select(literal_column("1"))
        .select_from(merged_child)
        .where(
            merged_child.canonical_visitor_id == Visitor.visitor_id,
            merged_child.site_id == Visitor.site_id,
            merged_child.identity_status == "merged",
        )
        .exists()
    )

    return and_(
        Visitor.is_agent_derived.is_(False),
        not_(
            and_(
                Visitor.is_imported_contact.is_(True),
                Visitor.total_pageviews == 0,
                not_(has_merged_child),
            )
        ),
    )
