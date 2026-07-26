"""Phase 2 — Meta connect → push → repeat-push, end to end (AC2 + AC6).

"Live" names the code path, NOT the network: every Meta call is mocked. The
OAuth callback is driven exactly like the CRM donor test
(test_crm_push.test_hubspot_oauth_roundtrip) — a real oauth_state token, the
real router handler, a real DB row — with MetaAdsProvider's transport
monkeypatched so no request ever leaves the process.

Requires local PostgreSQL + Redis (oauth_state).
"""

import uuid as uuidlib

import pytest
import pytest_asyncio
from sqlalchemy import func, select

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def meta_setup(test_db, monkeypatch):
    from apps.api.config import settings
    from apps.api.models.segment import Segment, SegmentMember
    from apps.api.models.site import Site
    from apps.api.models.user import User
    from apps.api.models.visitor import IdentifiedVisitor

    monkeypatch.setattr(settings, "mock_external_apis", True)
    monkeypatch.setattr(settings, "ad_audiences_enabled", True)

    user = User(
        email=f"ads-meta-{uuidlib.uuid4().hex[:8]}@test.com",
        hashed_password="x",
        full_name="Ads Meta",
    )
    test_db.add(user)
    await test_db.flush()

    site_id = f"ads_meta_{uuidlib.uuid4().hex[:8]}"
    test_db.add(
        Site(site_id=site_id, user_id=user.id, name="Meta", url="https://meta.example.com")
    )

    seg_id = uuidlib.uuid4()
    test_db.add(Segment(id=seg_id, site_id=site_id, name="Meta seg", visitor_count=3))
    for i in range(3):
        test_db.add(SegmentMember(segment_id=seg_id, visitor_id=f"mv{i}", site_id=site_id))
        test_db.add(
            IdentifiedVisitor(
                site_id=site_id,
                visitor_id=f"mv{i}",
                email=f"meta{i}@example.com",
                full_name="First Last",
                resolution_provider="form_capture",
            )
        )
    await test_db.commit()
    return {"user": user, "site_id": site_id, "segment_id": str(seg_id)}


async def _connect_via_callback(test_db, meta_setup):
    """Drive the real OAuth callback handler with a real state token (AC2)."""
    from apps.api.routers import ads as ads_router
    from apps.api.services.oauth_state import store_oauth_state

    user, site_id = meta_setup["user"], meta_setup["site_id"]
    state = uuidlib.uuid4().hex
    await store_oauth_state(state, f"{user.id}:{site_id}:meta")

    resp = await ads_router.oauth_callback(
        "meta", code="fake-auth-code", state=state, db=test_db
    )
    return resp


async def test_meta_oauth_callback_creates_a_connected_connection(test_db, meta_setup):
    from apps.api.models.ad_connection import AdConnection

    resp = await _connect_via_callback(test_db, meta_setup)
    assert "ads=connected" in str(resp.headers.get("location", ""))

    conn = (
        await test_db.execute(
            select(AdConnection).where(
                AdConnection.site_id == meta_setup["site_id"],
                AdConnection.provider == "meta",
            )
        )
    ).scalar_one()

    assert conn.status == "connected"
    assert conn.is_valid is True
    assert conn.ad_account_id == "act_mock"
    assert conn.last_error is None
    # Tokens are stored encrypted — the raw mock token must not be persisted.
    assert conn.access_token
    assert not conn.access_token.startswith("mock-meta-token-")


async def test_meta_connect_then_push_then_repeat_push_reuses_audience(
    test_db, meta_setup
):
    """AC2 → AC6 in one flow: connect, push, push again, same audience id."""
    from apps.api.models.ad_audience_link import AdAudienceLink
    from apps.api.models.ad_connection import AdConnection
    from apps.api.services.ads_push import push_segment_to_ads

    await _connect_via_callback(test_db, meta_setup)
    site_id, segment_id = meta_setup["site_id"], meta_setup["segment_id"]

    first = await push_segment_to_ads(test_db, site_id, "meta", segment_id)
    assert first.found is True
    assert first.pushed == 3
    assert first.platform_audience_id

    second = await push_segment_to_ads(test_db, site_id, "meta", segment_id)
    assert second.platform_audience_id == first.platform_audience_id, (
        "repeat push created a NEW Meta audience instead of reusing the link row"
    )

    link_count = await test_db.scalar(
        select(func.count())
        .select_from(AdAudienceLink)
        .where(AdAudienceLink.segment_id == segment_id)
    )
    assert link_count == 1

    conn = (
        await test_db.execute(
            select(AdConnection).where(
                AdConnection.site_id == site_id, AdConnection.provider == "meta"
            )
        )
    ).scalar_one()
    assert conn.status == "connected"
    assert conn.last_pushed_at is not None


async def test_small_segment_push_reports_the_structured_minimum_fields(
    test_db, meta_setup
):
    """AC7 backend leg — below_minimum/minimum_threshold accompany `warning`."""
    from apps.api.services.ads_push import MIN_AUDIENCE_SIZE, push_segment_to_ads

    await _connect_via_callback(test_db, meta_setup)
    outcome = await push_segment_to_ads(
        test_db, meta_setup["site_id"], "meta", meta_setup["segment_id"]
    )

    assert outcome.below_minimum is True  # 3 contacts << 1000
    assert outcome.minimum_threshold == MIN_AUDIENCE_SIZE
    assert str(MIN_AUDIENCE_SIZE) in outcome.warning
    assert "100" in outcome.warning  # technical floor is named too (D1)
    # Warned, never blocked.
    assert outcome.pushed == 3


async def test_tos_precondition_failure_surfaces_the_actionable_message(
    test_db, meta_setup, monkeypatch
):
    """AC13 — the ToS error keeps its specific copy + remediation URL."""
    from apps.api.models.ad_connection import AdConnection
    from apps.api.services.ads.meta import MetaAdsProvider, MetaAudienceTermsError
    from apps.api.services.ads_push import push_segment_to_ads

    await _connect_via_callback(test_db, meta_setup)

    async def blow_up(self, connection, link, hashed_contacts):
        raise MetaAudienceTermsError(
            "Meta rejected this push because this ad account hasn't accepted the "
            "Custom Audience Terms of Service yet. Accept them here, then try again: "
            "https://business.facebook.com/ads/manage/customaudiences/tos/?act=mock"
        )

    monkeypatch.setattr(MetaAdsProvider, "create_or_update_audience", blow_up)
    outcome = await push_segment_to_ads(
        test_db, meta_setup["site_id"], "meta", meta_setup["segment_id"]
    )

    assert outcome.errors, "the ToS failure produced no user-facing error"
    message = outcome.errors[0]
    assert "Custom Audience Terms" in message
    assert "customaudiences/tos/" in message
    assert "Provider returned HTTP" not in message, "collapsed into the generic branch"

    conn = (
        await test_db.execute(
            select(AdConnection).where(
                AdConnection.site_id == meta_setup["site_id"],
                AdConnection.provider == "meta",
            )
        )
    ).scalar_one()
    assert conn.status == "error"
    assert "customaudiences/tos/" in (conn.last_error or "")
