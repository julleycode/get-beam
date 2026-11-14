"""GDPR erasure-gap closures (needs Postgres).

- identity_feedback rows are erased by fingerprint on per-visitor DELETE, and
  on site delete; the response carries no identity_feedback count (no oracle).
- per-visitor DELETE removes the enrichment profile (and its social_context).
- KG-8: the cumulative daily cap answers 429 and touches nothing.
- retention purges: identity_feedback by age, social_context blob by age.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.dependencies import get_current_user
from apps.api.main import app
from apps.api.models.enrichment import EnrichmentProfile
from apps.api.models.erasure_request import ErasureRequest
from apps.api.models.identity_feedback import ANONYMOUS_USER_ID, IdentityFeedback
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.models.visitor import Visitor
from apps.api.services import graph_erasure as ge

pytestmark = pytest.mark.integration

SITE = "site_gdpr_gaps"
OTHER_SITE = "site_gdpr_other"
FP = "fp2_gdpr_target"
FP3 = "fp3_gdpr_target"


@pytest_asyncio.fixture
async def sessions(test_engine, monkeypatch):
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(ge, "async_session", factory)
    return factory


def _feedback(fp: str | None, site_id: str | None) -> IdentityFeedback:
    return IdentityFeedback(
        user_id=ANONYMOUS_USER_ID,
        site_id=site_id,
        fingerprint=fp,
        surface="public_onboarding_canary",
        shown={"city": "Hanoi"},
        reasons=["wrong_city"],
    )


@pytest_asyncio.fixture
async def user_client(test_client, sessions):
    user_id = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with sessions() as s:
        s.add(Site(site_id=SITE, user_id=user_id, name="S", url="https://gdpr.example.com"))
        s.add(
            Visitor(
                site_id=SITE,
                visitor_id="v-target",
                fingerprint=FP,
                fingerprint_v3=FP3,
                first_seen=now,
                last_seen=now,
                identity_status="anonymous",
            )
        )
        s.add(
            EnrichmentProfile(
                site_id=SITE,
                visitor_id="v-target",
                social_context={"recent_posts": [{"text": "personal post"}]},
            )
        )
        s.add_all(
            [
                _feedback(FP, None),  # public funnel, same device -> erased
                _feedback(FP3, SITE),  # this site, v3 fingerprint -> erased
                _feedback(FP, OTHER_SITE),  # another tenant's row -> kept
                _feedback("fp_unrelated", None),  # other device -> kept
            ]
        )
        await s.commit()
    app.dependency_overrides[get_current_user] = lambda: User(id=user_id, email="o@x.com")
    yield test_client
    app.dependency_overrides.pop(get_current_user, None)


async def _feedback_rows(s: AsyncSession) -> set[tuple]:
    rows = (await s.execute(select(IdentityFeedback))).scalars().all()
    return {(r.fingerprint, r.site_id) for r in rows}


@pytest.mark.asyncio
async def test_visitor_delete_erases_identity_feedback_by_fingerprint(user_client, sessions):
    resp = await user_client.delete(f"/api/v1/visitors/{SITE}/v-target/data")
    assert resp.status_code == 200
    # No identity_feedback count in the response: it would be an oracle for
    # site-less (Beam funnel) rows.
    assert "identity_feedback" not in resp.json()["deleted"]

    async with sessions() as s:
        assert await _feedback_rows(s) == {(FP, OTHER_SITE), ("fp_unrelated", None)}


@pytest.mark.asyncio
async def test_visitor_delete_removes_social_context(user_client, sessions):
    resp = await user_client.delete(f"/api/v1/visitors/{SITE}/v-target/data")
    assert resp.status_code == 200
    assert resp.json()["deleted"]["enrichment_profiles"] == 1
    async with sessions() as s:
        assert (
            await s.execute(
                select(EnrichmentProfile.id).where(EnrichmentProfile.site_id == SITE)
            )
        ).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_daily_cap_returns_429_and_deletes_nothing(user_client, sessions, monkeypatch):
    monkeypatch.setattr(ge.settings, "graph_erasure_max_per_day", 1)
    async with sessions() as s:
        s.add(
            ErasureRequest(
                requesting_site_id=SITE,
                visitor_id="earlier",
                targets=["beam_identity_graph"],
                status="done",
                attempts=1,
            )
        )
        await s.commit()

    resp = await user_client.delete(f"/api/v1/visitors/{SITE}/v-target/data")
    assert resp.status_code == 429
    assert resp.headers.get("retry-after") == "3600"

    async with sessions() as s:
        assert (
            await s.execute(select(Visitor.id).where(Visitor.visitor_id == "v-target"))
        ).scalar_one_or_none() is not None, "429 must not delete anything"
        n = len((await s.execute(select(ErasureRequest))).scalars().all())
        assert n == 1, "429 must not enqueue"


@pytest.mark.asyncio
async def test_daily_cap_counts_only_own_site(user_client, sessions, monkeypatch):
    monkeypatch.setattr(ge.settings, "graph_erasure_max_per_day", 1)
    async with sessions() as s:
        s.add(
            ErasureRequest(
                requesting_site_id=OTHER_SITE,
                visitor_id="x",
                targets=["beam_identity_graph"],
                status="done",
                attempts=1,
            )
        )
        await s.commit()
    resp = await user_client.delete(f"/api/v1/visitors/{SITE}/v-target/data")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_site_delete_erases_site_tagged_identity_feedback(user_client, sessions):
    resp = await user_client.delete(f"/api/v1/sites/{SITE}")
    assert resp.status_code == 204
    async with sessions() as s:
        rows = await _feedback_rows(s)
    assert (FP3, SITE) not in rows
    assert (FP, OTHER_SITE) in rows and (FP, None) in rows


# ─────────────────────────── retention ───────────────────────────


@pytest_asyncio.fixture
async def retention(test_engine):
    from apps.api.services import retention as mod

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    original = mod.async_session
    mod.async_session = factory
    yield mod, factory
    mod.async_session = original


@pytest.mark.asyncio
async def test_identity_feedback_retention_purge(retention):
    mod, factory = retention
    old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=120)
    async with factory() as s:
        stale = _feedback("fp_old", None)
        stale.created_at = old
        s.add_all([stale, _feedback("fp_new", None)])
        await s.commit()

    dry = await mod.purge_identity_feedback_older_than(days=90, dry_run=True)
    assert dry == {"status": "dry_run", "would_delete": 1}
    res = await mod.purge_identity_feedback_older_than(days=90)
    assert res == {"status": "ok", "deleted": 1}
    async with factory() as s:
        assert {r[0] for r in await _feedback_rows(s)} == {"fp_new"}
    assert (await mod.purge_identity_feedback_older_than(days=90))["deleted"] == 0


@pytest.mark.asyncio
async def test_social_context_retention_clears_blob_keeps_profile(retention):
    mod, factory = retention
    now = datetime.now(timezone.utc)
    async with factory() as s:
        s.add_all(
            [
                EnrichmentProfile(
                    site_id=SITE,
                    visitor_id="old",
                    social_context={"recent_posts": ["x"]},
                    social_context_updated_at=now - timedelta(days=200),
                    job_title="Kept Title",
                ),
                EnrichmentProfile(
                    site_id=SITE,
                    visitor_id="fresh",
                    social_context={"recent_posts": ["y"]},
                    social_context_updated_at=now - timedelta(days=5),
                ),
            ]
        )
        await s.commit()

    res = await mod.purge_social_context_older_than(days=180)
    assert res == {"status": "ok", "deleted": 1}
    async with factory() as s:
        rows = {
            p.visitor_id: p
            for p in (await s.execute(select(EnrichmentProfile))).scalars().all()
        }
    assert rows["old"].social_context is None and rows["old"].job_title == "Kept Title"
    assert rows["fresh"].social_context == {"recent_posts": ["y"]}
