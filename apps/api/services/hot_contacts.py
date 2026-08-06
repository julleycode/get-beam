"""Hot imported contacts (identity-honesty Phase 6).

Answers one dashboard question: "how many of my imported contacts are active,
and which ones" — e.g. "12 of your 500 imported contacts viewed pricing this
week". Read-only aggregation on top of data Phases 4 (import) and 5 (promotion
sweep) already produce; this module writes nothing.

POINTER SEMANTICS (the whole reason this file is not a one-line COUNT):
a phantom imported-contact ``Visitor`` row (``is_imported_contact = True``)
NEVER accrues traffic on its own columns. When the real person later visits and
identifies by the same email, ``identity_resolver._save_identified``'s
email-dedup branch marks the CLICK-DERIVED row ``identity_status = "merged"``
and points its ``canonical_visitor_id`` AT the phantom. The phantom's own
``last_seen`` / ``total_pageviews`` stay frozen at import time. So "active" must
be read off the merged CHILD, through that pointer — the join predicate is the
same one already proven in ``agent_visitor_filters.human_only_visitor_filter``'s
``has_merged_child`` EXISTS, reused here rather than reinvented.

COUNTING-SAFE BY CONSTRUCTION: one phantom can legitimately have MORE THAN ONE
merged child (same person, work laptop + phone, each pre-identification
``visitor_id`` merging onto the same email). A plain ``LEFT JOIN`` to the child
rows would fan out and count that single contact twice in "N". Every query here
therefore resolves activity with a CORRELATED SCALAR SUBQUERY
(``MAX(child.last_seen)``), which is structurally incapable of fan-out — no
GROUP BY / DISTINCT band-aid needed.
"""

from datetime import datetime, timedelta

from sqlalchemy import Select, desc, func, select
from sqlalchemy.orm import aliased

from apps.api.models.visitor import IdentifiedVisitor, Visitor

# "Active this week". Kept as a module constant so the query, the endpoint
# default and the tests agree on one number.
DEFAULT_ACTIVITY_WINDOW_DAYS = 7

# Cap on the drill-down list. The count is always exact and unlimited; only the
# returned rows are bounded, so a 5,000-contact site can't produce a huge body.
MAX_HOT_CONTACTS_RETURNED = 100


def activity_last_seen_subquery():
    """Correlated scalar subquery: newest merged-child ``last_seen`` per phantom.

    NULL when the phantom has no merged child at all (never visited). Correlated
    on the OUTER ``Visitor`` row, so it yields exactly one value per phantom —
    this is the counting-safe form required over a fan-out-prone LEFT JOIN.
    """
    merged_child = aliased(Visitor)
    return (
        select(func.max(merged_child.last_seen))
        .where(
            merged_child.canonical_visitor_id == Visitor.visitor_id,
            merged_child.site_id == Visitor.site_id,
            merged_child.identity_status == "merged",
        )
        .correlate(Visitor)
        .scalar_subquery()
    )


def _cutoff(days: int) -> datetime:
    return datetime.utcnow() - timedelta(days=days)


def imported_contacts_total_query(site_id: str) -> Select:
    """The "of M" denominator: every imported contact on this site.

    No join — an imported contact counts toward M whether or not it is active.
    """
    return select(func.count(Visitor.visitor_id)).where(
        Visitor.site_id == site_id,
        Visitor.is_imported_contact.is_(True),
    )


def hot_contacts_count_query(site_id: str, days: int = DEFAULT_ACTIVITY_WINDOW_DAYS) -> Select:
    """The "N" numerator: imported contacts active inside the window.

    Counts PHANTOM rows, with activity resolved via the correlated subquery, so
    a phantom with two merged children is counted exactly ONCE. A phantom with
    no merged child yields NULL and fails the ``>`` comparison — excluded, as
    required by Step B3 (never "active" through its own dormant columns).
    """
    activity = activity_last_seen_subquery()
    return select(func.count(Visitor.visitor_id)).where(
        Visitor.site_id == site_id,
        Visitor.is_imported_contact.is_(True),
        activity.is_not(None),
        activity > _cutoff(days),
    )


def hot_contacts_list_query(
    site_id: str,
    days: int = DEFAULT_ACTIVITY_WINDOW_DAYS,
    limit: int = MAX_HOT_CONTACTS_RETURNED,
) -> Select:
    """Drill-down rows for the active contacts, newest activity first.

    The ``IdentifiedVisitor`` join is 1:1 (unique on site_id + visitor_id), so it
    adds no fan-out risk; the activity value still comes from the correlated
    subquery, never from a joined child row.
    """
    activity = activity_last_seen_subquery()
    return (
        select(
            Visitor.visitor_id,
            IdentifiedVisitor.email,
            IdentifiedVisitor.full_name,
            activity.label("activity_last_seen"),
        )
        .join(
            IdentifiedVisitor,
            (IdentifiedVisitor.site_id == Visitor.site_id)
            & (IdentifiedVisitor.visitor_id == Visitor.visitor_id),
            isouter=True,
        )
        .where(
            Visitor.site_id == site_id,
            Visitor.is_imported_contact.is_(True),
            activity.is_not(None),
            activity > _cutoff(days),
        )
        .order_by(desc(activity))
        .limit(limit)
    )


async def hot_contacts_summary(
    db,
    site_id: str,
    days: int = DEFAULT_ACTIVITY_WINDOW_DAYS,
    limit: int = MAX_HOT_CONTACTS_RETURNED,
) -> dict:
    """"N of your M imported contacts active this week", plus the N rows.

    Caller is responsible for site ownership (``verify_site_access``); every
    query here is additionally scoped by ``site_id``, so a wrong id returns
    zeroes rather than another tenant's data.
    """
    total = (await db.execute(imported_contacts_total_query(site_id))).scalar_one()
    active = (await db.execute(hot_contacts_count_query(site_id, days))).scalar_one()
    rows = (await db.execute(hot_contacts_list_query(site_id, days, limit))).all()
    return {
        "active_count": int(active or 0),
        "total_count": int(total or 0),
        "window_days": days,
        "contacts": [
            {
                "visitor_id": visitor_id,
                # Plaintext to the site owner — this is their own uploaded data,
                # matching every other Visitors-dashboard response. mask_email()
                # is for log lines only.
                "email": email,
                "full_name": full_name,
                "last_activity_at": last_activity,
            }
            for visitor_id, email, full_name, last_activity in rows
        ],
    }


# ─────────────────── Job-change events (job-change-detection v1) ──────────────
#
# DELIBERATELY NOT built on the phantom-pointer query family above. That
# machinery (correlated MAX(child.last_seen) through canonical_visitor_id)
# exists to solve one specific problem: a phantom imported-contact row accrues
# no traffic on its own columns, so "active" has to be read off a merged CHILD.
# A JobChangeEvent row has no such indirection — it is written directly against
# a real (site_id, visitor_id) pair at detection time, so a plain site-scoped
# ORDER BY is both correct and counting-safe.
#
# Stated explicitly so a future reader does not "unify" the two query families
# and reintroduce pointer semantics where none are needed.

# Cap on the returned job-change feed, mirroring MAX_HOT_CONTACTS_RETURNED's
# intent: the dashboard shows a recent-activity list, not an unbounded history.
MAX_JOB_CHANGES_RETURNED = 50


async def get_job_change_events(db, site_id: str, limit: int = MAX_JOB_CHANGES_RETURNED):
    """Most recent confirmed job changes for one site, newest first.

    Read-only. Site-scoped, so a wrong or foreign ``site_id`` yields an empty
    list rather than another tenant's data (the caller still owns the
    ``verify_site_access`` check). Returns [] for every site while job-change
    detection is disabled.
    """
    from apps.api.models.job_change_event import JobChangeEvent

    rows = (
        await db.execute(
            select(JobChangeEvent)
            .where(JobChangeEvent.site_id == site_id)
            .order_by(desc(JobChangeEvent.detected_at))
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)
