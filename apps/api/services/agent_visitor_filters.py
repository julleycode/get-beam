"""Shared human-only visitor predicate (EvalLayer Phase 05, GUARD #2 / SPEC AC2).

Agent-company-resolution creates synthetic ``Visitor`` rows (``is_agent_derived
= True``) so an agent visit's IP can run through the existing identity-resolution
waterfall. Those rows must NEVER appear in any human-facing surface — visitor
lists, stats, resolution eligibility, segmentation, or aggregation.

Every human-data query site imports and calls ``human_only_visitor_filter()``
instead of hand-copying ``Visitor.is_agent_derived.is_(False)``. A single choke
point means a future change to the exclusion semantics (e.g. a second condition)
touches exactly one place.
"""


def human_only_visitor_filter():
    """SQLAlchemy predicate excluding agent-derived synthetic Visitor rows.

    Use at every human-data query site::

        from apps.api.services.agent_visitor_filters import human_only_visitor_filter
        select(Visitor).where(..., human_only_visitor_filter())
    """
    from apps.api.models.visitor import Visitor

    return Visitor.is_agent_derived.is_(False)
