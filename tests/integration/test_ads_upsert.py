"""AC6 (mock-mode leg) — repeat push updates, never duplicates.

Pushing the same segment twice must reuse the platform audience recorded on the
first push instead of creating a second one. The mechanism is the
(connection_id, segment_id) unique constraint plus an
ON CONFLICT ... DO UPDATE upsert in services/ads_push.py.

Full AC6 credit (live platform confirmation) belongs to Phase 2/3 — this is the
mock-mode leg only. Requires local PostgreSQL.
"""

import uuid as uuidlib

import pytest
import pytest_asyncio
from sqlalchemy import func, select

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def upsert_setup(test_db, monkeypatch):
    from apps.api.config import settings
    from apps.api.models.ad_connection import AdConnection
    from apps.api.models.segment import Segment, SegmentMember
    from apps.api.models.site import Site
    from apps.api.models.user import User
    from apps.api.models.visitor import IdentifiedVisitor

    monkeypatch.setattr(settings, "mock_external_apis", True)
    monkeypatch.setattr(settings, "ad_audiences_enabled", True)

    user = User(
        email=f"ads-upsert-{uuidlib.uuid4().hex[:8]}@test.com",
        hashed_password="x", full_name="Ads Upsert",
    )
    test_db.add(user)
    await test_db.flush()

    site_id = f"ads_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=site_id, user_id=user.id, name="Ads", url="https://ads.example.com"))

    seg_id = uuidlib.uuid4()
    test_db.add(Segment(id=seg_id, site_id=site_id, name="Repeat", visitor_count=2))
    for i in range(2):
        test_db.add(SegmentMember(segment_id=seg_id, visitor_id=f"v{i}", site_id=site_id))
        test_db.add(
            IdentifiedVisitor(
                site_id=site_id, visitor_id=f"v{i}", email=f"u{i}@example.com",
                full_name="First Last", resolution_provider="form_capture",
            )
        )

    conn_id = uuidlib.uuid4()
    test_db.add(
        AdConnection(
            id=conn_id, site_id=site_id, user_id=user.id, provider="meta",
            auth_type="oauth", status="connected",
        )
    )
    await test_db.commit()
    return {"site_id": site_id, "segment_id": str(seg_id), "connection_id": conn_id}


async def test_ads_upsert_repeat_push_reuses_platform_audience_id(test_db, upsert_setup):
    from apps.api.models.ad_audience_link import AdAudienceLink
    from apps.api.services.ads_push import push_segment_to_ads

    site_id, segment_id = upsert_setup["site_id"], upsert_setup["segment_id"]

    first = await push_segment_to_ads(test_db, site_id, "meta", segment_id)
    assert first.platform_audience_id.startswith("mock-meta-aud-")

    second = await push_segment_to_ads(test_db, site_id, "meta", segment_id)
    assert second.platform_audience_id == first.platform_audience_id, (
        "repeat push created a NEW platform audience instead of updating"
    )

    # Exactly one link row for this (connection, segment) pair.
    count = await test_db.scalar(
        select(func.count()).select_from(AdAudienceLink).where(
            AdAudienceLink.connection_id == upsert_setup["connection_id"],
            AdAudienceLink.segment_id == segment_id,
        )
    )
    assert count == 1

    link = (
        await test_db.execute(
            select(AdAudienceLink).where(
                AdAudienceLink.connection_id == upsert_setup["connection_id"],
                AdAudienceLink.segment_id == segment_id,
            )
        )
    ).scalar_one()
    assert link.platform_audience_id == first.platform_audience_id
    assert link.last_push_count == 2
    assert link.last_pushed_at is not None


async def test_ads_upsert_different_segment_gets_its_own_audience(test_db, upsert_setup):
    from apps.api.models.ad_audience_link import AdAudienceLink
    from apps.api.models.segment import Segment, SegmentMember
    from apps.api.models.visitor import IdentifiedVisitor
    from apps.api.services.ads_push import push_segment_to_ads

    site_id = upsert_setup["site_id"]
    other_seg = uuidlib.uuid4()
    test_db.add(Segment(id=other_seg, site_id=site_id, name="Other", visitor_count=1))
    test_db.add(SegmentMember(segment_id=other_seg, visitor_id="vX", site_id=site_id))
    test_db.add(
        IdentifiedVisitor(
            site_id=site_id, visitor_id="vX", email="other@example.com",
            full_name="First Last", resolution_provider="form_capture",
        )
    )
    await test_db.commit()

    a = await push_segment_to_ads(test_db, site_id, "meta", upsert_setup["segment_id"])
    b = await push_segment_to_ads(test_db, site_id, "meta", str(other_seg))
    assert a.platform_audience_id != b.platform_audience_id

    total = await test_db.scalar(
        select(func.count()).select_from(AdAudienceLink).where(
            AdAudienceLink.connection_id == upsert_setup["connection_id"]
        )
    )
    assert total == 2
