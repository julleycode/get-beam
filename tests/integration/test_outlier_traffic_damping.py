"""Integration tests for outlier / internal-traffic damping (AC1, AC3-AC5, AC7).

Requires: PostgreSQL + Redis running locally
(``docker compose -f infra/docker-compose.yml up -d postgres redis``).

Unit-level coverage for the pure scoring math and the structural-isolation
checks lives in ``tests/unit/test_outlier_traffic_damping.py``. This file proves
the DB-facing behaviour:

  * the HUMAN-CONFIRMED visitor (internal_override == "internal") is EXCLUDED
    from daily_digest's cross-visitor aggregate while their row survives
    untouched (flag-but-store)
  * the HUMAN-CONFIRMED visitor is DEPRIORITISED (never excluded) in the
    resolution eligibility query
  * an AUTO-FLAGGED but UNCONFIRMED visitor (is_internal_suspect=True,
    internal_override=NULL) is fully counted and normally prioritised — the
    suggestion-only guarantee
  * clearing the confirmation genuinely RESTORES both — the reversibility guarantee
  * a manual override wins over a later sweep in BOTH directions
  * a damping-OFF site sees byte-identical behaviour
"""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration

_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
)


@pytest_asyncio.fixture
async def damping_site(test_db):
    """A site with damping ON, plus a sibling site with damping OFF."""
    from apps.api.models.site import Site
    from apps.api.models.user import User

    result = await test_db.execute(
        select(User).where(User.email == "test-outlier@test.com")
    )
    user = result.scalar_one_or_none()
    if not user:
        user = User(email="test-outlier@test.com", full_name="Outlier Test User")
        test_db.add(user)
        await test_db.flush()

    made = {}
    for site_id, enabled in (
        ("test_site_outlier_on", True),
        ("test_site_outlier_off", False),
    ):
        result = await test_db.execute(select(Site).where(Site.site_id == site_id))
        site = result.scalar_one_or_none()
        if not site:
            site = Site(
                site_id=site_id,
                user_id=user.id,
                name=f"Outlier Test {site_id}",
                url=f"https://{site_id}.example.com",
            )
            test_db.add(site)
        site.internal_damping_enabled = enabled
        await test_db.flush()
        made[site_id] = site

    await test_db.commit()
    return made


async def _seed_visitor(
    db,
    site_id: str,
    visitor_id: str,
    *,
    days: int,
    events_per_day: list[str],
    pageviews: int = 1,
    intent_score: int = 10,
    flagged: bool = False,
    override: str | None = None,
):
    from apps.api.models.event import Event
    from apps.api.models.visitor import Visitor

    base = datetime.utcnow() - timedelta(days=days + 1)
    for day in range(days):
        stamp = base + timedelta(days=day)
        for event_type in events_per_day:
            db.add(
                Event(
                    site_id=site_id,
                    visitor_id=visitor_id,
                    event_type=event_type,
                    user_agent=_BROWSER_UA,
                    created_at=stamp,
                )
            )

    db.add(
        Visitor(
            site_id=site_id,
            visitor_id=visitor_id,
            first_seen=base,
            last_seen=datetime.utcnow(),
            total_pageviews=pageviews,
            intent_score=intent_score,
            identity_status="anonymous",
            is_internal_suspect=flagged,
            internal_override=override,
        )
    )
    await db.commit()


async def _digest_stats(db, site_id: str, damping_enabled: bool):
    from apps.api.services.daily_digest import _site_day_stats

    cutoff = datetime.utcnow() - timedelta(days=30)
    return await _site_day_stats(db, site_id, cutoff, damping_enabled)


async def _get_visitor(db, site_id: str, visitor_id: str):
    from apps.api.models.visitor import Visitor

    result = await db.execute(
        select(Visitor).where(
            Visitor.site_id == site_id, Visitor.visitor_id == visitor_id
        )
    )
    return result.scalar_one()


# ─── AC4: cross-visitor aggregate exclusion + flag-but-store ───


@pytest.mark.asyncio
async def test_confirmed_visitor_excluded_from_digest_but_row_survives(
    test_db, damping_site
):
    site_id = "test_site_outlier_on"
    await _seed_visitor(
        test_db, site_id, "normal_a", days=2, events_per_day=["pageview"], pageviews=10
    )
    await _seed_visitor(
        test_db,
        site_id,
        "heavy_one",
        days=2,
        events_per_day=["pageview"],
        pageviews=5000,
        flagged=True,
        override="internal",
    )

    stats = await _digest_stats(test_db, site_id, damping_enabled=True)

    assert stats.pageviews == 10, "the outlier's 5,000 pageviews must not dominate"
    assert stats.new_visitors == 1

    # Flag-but-store: the row is fully intact, never deleted.
    heavy = await _get_visitor(test_db, site_id, "heavy_one")
    assert heavy is not None
    assert heavy.total_pageviews == 5000
    assert heavy.is_internal_suspect is True


@pytest.mark.asyncio
async def test_auto_flagged_but_unconfirmed_visitor_is_still_fully_counted(
    test_db, damping_site
):
    """SUGGESTION-ONLY: the scorer's label alone must change no aggregate.

    Calibrated live 27-07-26: auto-excluding at 20x would have hidden 5 of the
    28 identified visitors in the whole system (~18% of real leads).
    """
    site_id = "test_site_outlier_on"
    await _seed_visitor(
        test_db, site_id, "sugg_normal", days=2, events_per_day=["pageview"], pageviews=10
    )
    await _seed_visitor(
        test_db,
        site_id,
        "sugg_heavy",
        days=2,
        events_per_day=["pageview"],
        pageviews=5000,
        flagged=True,
        override=None,
    )

    stats = await _digest_stats(test_db, site_id, damping_enabled=True)

    assert stats.pageviews == 5010, (
        "an auto-flagged but unconfirmed visitor must stay fully counted"
    )
    assert stats.new_visitors == 2


@pytest.mark.asyncio
async def test_damping_off_site_sees_identical_digest_numbers(test_db, damping_site):
    site_id = "test_site_outlier_off"
    await _seed_visitor(
        test_db, site_id, "off_normal", days=2, events_per_day=["pageview"], pageviews=10
    )
    await _seed_visitor(
        test_db,
        site_id,
        "off_heavy",
        days=2,
        events_per_day=["pageview"],
        pageviews=5000,
        flagged=True,
        override="internal",
    )

    stats = await _digest_stats(test_db, site_id, damping_enabled=False)

    assert stats.pageviews == 5010, "damping-OFF must be byte-identical to pre-feature"
    assert stats.new_visitors == 2


@pytest.mark.asyncio
async def test_clearing_the_confirmation_restores_the_visitor_to_the_aggregate(
    test_db, damping_site
):
    """REVERSIBILITY: clearing must genuinely restore, not just flip a field."""
    site_id = "test_site_outlier_on"
    await _seed_visitor(
        test_db,
        site_id,
        "reversible_one",
        days=2,
        events_per_day=["pageview"],
        pageviews=800,
        flagged=True,
        override="internal",
    )

    before = await _digest_stats(test_db, site_id, damping_enabled=True)
    assert before.pageviews == 0

    visitor = await _get_visitor(test_db, site_id, "reversible_one")
    visitor.internal_override = None
    await test_db.commit()

    after = await _digest_stats(test_db, site_id, damping_enabled=True)
    assert after.pageviews == 800, (
        "undoing the confirmation must restore the aggregate — and note the "
        "still-True is_internal_suspect label alone does not exclude"
    )


# ─── AC5: resolution deprioritisation, never exclusion ───


async def _eligibility_order(db, site) -> list[str]:
    """The exact ordering resolution_runner applies, without doing paid work."""
    from apps.api.models.visitor import Visitor
    from apps.api.services.agent_visitor_filters import human_only_visitor_filter
    from apps.api.services.resolution_eligibility import resolution_intent_filter

    order_by = (
        (
            Visitor.internal_override.is_distinct_from("internal").desc(),
            Visitor.intent_score.desc(),
        )
        if site.internal_damping_enabled
        else (Visitor.intent_score.desc(),)
    )
    result = await db.execute(
        select(Visitor.visitor_id)
        .where(
            Visitor.site_id == site.site_id,
            Visitor.identity_status == "anonymous",
            resolution_intent_filter([]),
            Visitor.do_not_resolve.is_(False),
            human_only_visitor_filter(),
        )
        .order_by(*order_by)
    )
    return [vid for (vid,) in result.all()]


@pytest.mark.asyncio
async def test_confirmed_visitor_sorts_last_but_is_still_eligible(test_db, damping_site):
    site = damping_site["test_site_outlier_on"]
    await _seed_visitor(
        test_db,
        site.site_id,
        "res_heavy",
        days=2,
        events_per_day=["pageview"],
        intent_score=95,
        flagged=True,
        override="internal",
    )
    await _seed_visitor(
        test_db,
        site.site_id,
        "res_normal",
        days=2,
        events_per_day=["pageview"],
        intent_score=30,
    )

    order = await _eligibility_order(test_db, site)

    assert "res_heavy" in order, "deprioritised, NEVER excluded — budget may still reach them"
    assert order.index("res_normal") < order.index("res_heavy"), (
        "the confirmed-internal visitor must not keep eating the budget first"
    )


@pytest.mark.asyncio
async def test_auto_flagged_but_unconfirmed_visitor_keeps_normal_priority(
    test_db, damping_site
):
    """SUGGESTION-ONLY, second surface: the label alone must not reorder anyone."""
    site = damping_site["test_site_outlier_on"]
    await _seed_visitor(
        test_db,
        site.site_id,
        "sugg_res_heavy",
        days=2,
        events_per_day=["pageview"],
        intent_score=95,
        flagged=True,
        override=None,
    )
    await _seed_visitor(
        test_db,
        site.site_id,
        "sugg_res_normal",
        days=2,
        events_per_day=["pageview"],
        intent_score=30,
    )

    order = await _eligibility_order(test_db, site)

    assert order.index("sugg_res_heavy") < order.index("sugg_res_normal"), (
        "an auto-flagged but unconfirmed visitor must keep pure intent ordering"
    )


@pytest.mark.asyncio
async def test_damping_off_site_keeps_pure_intent_ordering(test_db, damping_site):
    site = damping_site["test_site_outlier_off"]
    await _seed_visitor(
        test_db,
        site.site_id,
        "off_res_heavy",
        days=2,
        events_per_day=["pageview"],
        intent_score=95,
        flagged=True,
        override="internal",
    )
    await _seed_visitor(
        test_db,
        site.site_id,
        "off_res_normal",
        days=2,
        events_per_day=["pageview"],
        intent_score=30,
    )

    order = await _eligibility_order(test_db, site)
    assert order.index("off_res_heavy") < order.index("off_res_normal")


@pytest.mark.asyncio
async def test_clearing_the_confirmation_restores_resolution_priority(
    test_db, damping_site
):
    """REVERSIBILITY, second surface: back to the front of the queue."""
    site = damping_site["test_site_outlier_on"]
    await _seed_visitor(
        test_db,
        site.site_id,
        "rev_res_heavy",
        days=2,
        events_per_day=["pageview"],
        intent_score=95,
        flagged=True,
        override="internal",
    )
    await _seed_visitor(
        test_db,
        site.site_id,
        "rev_res_normal",
        days=2,
        events_per_day=["pageview"],
        intent_score=30,
    )

    before = await _eligibility_order(test_db, site)
    assert before.index("rev_res_normal") < before.index("rev_res_heavy")

    visitor = await _get_visitor(test_db, site.site_id, "rev_res_heavy")
    visitor.internal_override = None
    await test_db.commit()

    after = await _eligibility_order(test_db, site)
    assert after.index("rev_res_heavy") < after.index("rev_res_normal"), (
        "clearing must restore the visitor to the front of the resolution queue"
    )


# ─── AC3 / AC7: manual override wins over the sweep, in BOTH directions ───


async def _run_sweep(db):
    from apps.api.services.outlier_traffic_damping_sweep import (
        run_outlier_traffic_damping_sweep,
    )

    return await run_outlier_traffic_damping_sweep(db)


@pytest.mark.asyncio
async def test_sweep_never_overwrites_a_manual_override_in_either_direction(
    test_db, damping_site, monkeypatch
):
    from apps.api.config import settings

    site_id = "test_site_outlier_on"

    # Enough normal visitors to clear the site sample floor, with a low median.
    for i in range(25):
        await _seed_visitor(
            test_db, site_id, f"ov_normal_{i}", days=6, events_per_day=["pageview"]
        )

    # A visitor a raw sweep WOULD flag (huge volume, sustained, engaged), but the
    # human already said "not internal".
    await _seed_visitor(
        test_db,
        site_id,
        "ov_says_not_internal",
        days=6,
        events_per_day=["pageview"] * 60 + ["scroll"] * 40,
        override="not_internal",
        flagged=False,
    )
    # A visitor a raw sweep would NOT flag (ordinary volume), but the human
    # already said "this is my team".
    await _seed_visitor(
        test_db,
        site_id,
        "ov_says_internal",
        days=6,
        events_per_day=["pageview"],
        override="internal",
        flagged=True,
    )

    monkeypatch.setattr(
        settings, "outlier_traffic_damping_min_site_visitors", 20, raising=False
    )
    monkeypatch.setattr(
        settings, "outlier_traffic_damping_min_visit_days", 5, raising=False
    )
    counters = await _run_sweep(test_db)
    assert counters["skipped_override"] >= 2

    not_internal = await _get_visitor(test_db, site_id, "ov_says_not_internal")
    says_internal = await _get_visitor(test_db, site_id, "ov_says_internal")

    assert not_internal.is_internal_suspect is False, "sweep re-flagged a human 'no'"
    assert not_internal.internal_override == "not_internal"
    assert says_internal.is_internal_suspect is True, "sweep un-set a human 'yes'"
    assert says_internal.internal_override == "internal"


@pytest.mark.asyncio
async def test_sweep_is_a_noop_when_no_site_has_opted_in(test_db, damping_site):
    from apps.api.models.site import Site

    for site in damping_site.values():
        site.internal_damping_enabled = False
    # Any other site created by a sibling test must not leak into this check.
    result = await test_db.execute(
        select(Site).where(Site.internal_damping_enabled.is_(True))
    )
    for site in result.scalars().all():
        site.internal_damping_enabled = False
    await test_db.commit()

    counters = await _run_sweep(test_db)
    assert counters == {
        "sites": 0,
        "flagged": 0,
        "cleared": 0,
        "skipped_override": 0,
    }
