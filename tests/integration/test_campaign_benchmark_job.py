"""Campaign benchmark weekly job — DB-truth legs (needs Postgres).

marketing-claims-gap Phase 3. Precondition:
``docker compose -f infra/docker-compose.yml up -d postgres redis``.

Flag posture is load-bearing here. `campaign_benchmark_enabled` gates whether
the data under test exists at all, so a run entirely flag-OFF proves nothing:

* AC-4 / AC-5 / AC-6 / AC-9 legs run with the flag ON (monkeypatched).
* AC-7 runs with the flag OFF and asserts ZERO rows — meaningful only as the
  pair of the flag-ON run above.

Covered:

- AC-4  a category pooling <5 opted-in sites writes NO row at all
- AC-4  a category pooling >=5 opted-in sites writes exactly one pooled row
- AC-5  a site with benchmark_contribution_enabled False/NULL contributes
        nothing and leaves no per-site trace
- AC-5  the identity co-op's Site.contribution_enabled is never read or written
- AC-6  the weekly job is registered in APScheduler when the flag is ON
- AC-7  flag OFF ⇒ zero rows written
- AC-13 the benchmark rollup filters to channel="email" (social rows excluded)
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.config import settings
from apps.api.main import app  # noqa: F401 — mapper registry
from apps.api.models.campaign import Campaign, CampaignTouchpoint
from apps.api.models.campaign_benchmark import CampaignBenchmark
from apps.api.models.site import Site
from apps.api.services import campaign_benchmark as bench

pytestmark = pytest.mark.integration

_NOW = datetime.now(timezone.utc).replace(tzinfo=None)
_SENT_AT = _NOW - timedelta(days=1)


@pytest_asyncio.fixture
async def sessions(test_engine):
    return async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def _seed_site(
    s: AsyncSession,
    site_id: str,
    category: str,
    *,
    opted_in: bool,
    sends: int = 4,
    opens: int = 2,
    clicks: int = 1,
    social_rows: int = 0,
) -> None:
    """One site with `sends` email touchpoints (plus optional SOCIAL rows).

    The social rows are constructed DIRECTLY via the ORM on purpose: no
    application path emits one (campaign_sender hardcodes channel="email"), and
    the send path is read-only in this phase — so a synthetic row is the only
    way to make the channel filter's assertion non-vacuous.
    """
    s.add(
        Site(
            site_id=site_id,
            user_id=uuid.uuid4(),
            name=site_id,
            url=f"https://{site_id}.example.com",
            category=category,
            benchmark_contribution_enabled=opted_in,
        )
    )
    campaign = Campaign(
        site_id=site_id, name=f"c-{site_id}", status="active", plan={"touchpoints": []}
    )
    s.add(campaign)
    await s.flush()
    for i in range(sends):
        s.add(
            CampaignTouchpoint(
                campaign_id=campaign.id,
                visitor_id=f"v-{site_id}-{i}",
                channel="email",
                touchpoint_order=1,
                status="sent",
                content={},
                sent_at=_SENT_AT,
                opened_at=_SENT_AT if i < opens else None,
                clicked_at=_SENT_AT if i < clicks else None,
            )
        )
    for i in range(social_rows):
        s.add(
            CampaignTouchpoint(
                campaign_id=campaign.id,
                visitor_id=f"v-{site_id}-social-{i}",
                channel="social_reply",
                touchpoint_order=2,
                status="sent",
                content={},
                sent_at=_SENT_AT,
                opened_at=_SENT_AT,
                clicked_at=_SENT_AT,
            )
        )
    await s.commit()


async def _rows(s: AsyncSession) -> list[CampaignBenchmark]:
    return list((await s.execute(select(CampaignBenchmark))).scalars().all())


# ── AC-4 / AC-13 — k-floor and channel filter, flag ON ──


@pytest.mark.asyncio
async def test_k_floor_pools_at_five_sites_and_discards_below(
    sessions, monkeypatch
):
    monkeypatch.setattr(settings, "campaign_benchmark_enabled", True)
    async with sessions() as s:
        # 5 opted-in SaaS sites -> clears the floor.
        for i in range(5):
            await _seed_site(s, f"site_saas_{i}", "Software", opted_in=True)
        # 2 opted-in agency sites -> below the floor, must produce NO row.
        for i in range(2):
            await _seed_site(s, f"site_agency_{i}", "Marketing agency", opted_in=True)

    written = await _run_job(sessions)
    assert written == 1

    async with sessions() as s:
        rows = await _rows(s)
        assert [r.category_normalized for r in rows] == ["saas"]
        row = rows[0]
        assert row.site_count == 5
        assert row.sends == 20  # 5 sites x 4 email sends
        assert row.opens == 10
        assert row.clicks == 5
        # The sub-floor category is DISCARDED, not written as a suppressed row.
        assert not [r for r in rows if r.category_normalized == "agency"]


@pytest.mark.asyncio
async def test_social_touchpoints_are_excluded_from_the_pooled_counters(
    sessions, monkeypatch
):
    monkeypatch.setattr(settings, "campaign_benchmark_enabled", True)
    async with sessions() as s:
        for i in range(5):
            await _seed_site(
                s, f"site_mixed_{i}", "Software", opted_in=True, social_rows=3
            )

    await _run_job(sessions)
    async with sessions() as s:
        row = (await _rows(s))[0]
        # 5 x 4 email sends only — the 15 social rows must not inflate anything.
        assert row.sends == 20
        assert row.opens == 10


# ── AC-5 — opt-out contributes nothing, co-op path untouched ──


@pytest.mark.asyncio
async def test_opted_out_and_null_sites_contribute_nothing(sessions, monkeypatch):
    monkeypatch.setattr(settings, "campaign_benchmark_enabled", True)
    async with sessions() as s:
        for i in range(5):
            await _seed_site(s, f"site_out_{i}", "Software", opted_in=False)
        # Also cover the pre-migration NULL case explicitly.
        await _seed_site(s, "site_null", "Software", opted_in=None)

    written = await _run_job(sessions)
    assert written == 0
    async with sessions() as s:
        assert await _rows(s) == []


@pytest.mark.asyncio
async def test_opt_in_flag_is_independent_of_the_identity_coop_flag(
    sessions, monkeypatch
):
    """A co-op contributor is NOT enrolled in the benchmark, and vice versa."""
    monkeypatch.setattr(settings, "campaign_benchmark_enabled", True)
    async with sessions() as s:
        for i in range(5):
            await _seed_site(s, f"site_coop_{i}", "Software", opted_in=False)
        # Flip only the CO-OP flag on all five.
        for i in range(5):
            site = (
                await s.execute(select(Site).where(Site.site_id == f"site_coop_{i}"))
            ).scalar_one()
            site.contribution_enabled = True
        await s.commit()

    written = await _run_job(sessions)
    assert written == 0  # co-op consent does not authorize benchmark pooling

    async with sessions() as s:
        # And the benchmark job left the co-op flag untouched.
        flags = (
            (await s.execute(select(Site.contribution_enabled))).scalars().all()
        )
        assert all(f is True for f in flags)


# ── AC-7 — flag OFF is inert (paired with the flag-ON runs above) ──


@pytest.mark.asyncio
async def test_flag_off_writes_zero_rows(sessions, monkeypatch):
    monkeypatch.setattr(settings, "campaign_benchmark_enabled", False)
    async with sessions() as s:
        for i in range(5):
            await _seed_site(s, f"site_off_{i}", "Software", opted_in=True)

    written = await _run_job(sessions)
    assert written == 0
    async with sessions() as s:
        assert (
            await s.execute(select(func.count()).select_from(CampaignBenchmark))
        ).scalar_one() == 0


# ── AC-6 — scheduler registration is flag-gated ──


@pytest.mark.asyncio
async def test_weekly_job_is_registered_only_when_the_flag_is_on(monkeypatch):
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from apps.api.jobs import scheduler as sched_mod

    for enabled, expect_job in ((True, True), (False, False)):
        monkeypatch.setattr(settings, "campaign_benchmark_enabled", enabled)
        sched = AsyncIOScheduler()
        monkeypatch.setattr(sched_mod, "scheduler", sched)
        sched_mod.start_scheduler()
        try:
            job = sched.get_job("campaign_benchmark")
            assert (job is not None) is expect_job
            if job is not None:
                # Deliberately clear of the Monday 15:00 UTC outcome digest.
                assert "sun" in str(job.trigger)
        finally:
            sched.shutdown(wait=False)


@pytest.mark.asyncio
async def test_job_wrapper_logs_and_survives_a_crash(monkeypatch):
    """AC-6: a crash inside the job must not propagate and kill the scheduler."""
    from apps.api.jobs import scheduler as sched_mod

    async def boom():
        raise RuntimeError("kaboom")

    monkeypatch.setattr(bench, "aggregate_weekly_benchmarks", boom)
    await sched_mod._campaign_benchmark_job()  # must NOT raise


async def _run_job(sessions) -> int:
    """Run the aggregation against the test sessionmaker."""
    import apps.api.services.campaign_benchmark as module

    original = module.async_session
    module.async_session = sessions
    try:
        return await module.aggregate_weekly_benchmarks()
    finally:
        module.async_session = original
