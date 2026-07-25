"""AC7 (mock-mode leg) — small-segment warning.

The push response carries a `warning` field when the matched audience is below
the platform-minimum placeholder (services.ads_push.MIN_AUDIENCE_SIZE, 1000 per
SPEC OQ5). The warning is advisory — the push still happens.

Real per-platform minimums are a Phase 2/3 docs-fetch item; this proves the
mechanism, not the number. Requires local PostgreSQL.
"""

import uuid as uuidlib

import pytest
import pytest_asyncio

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def warning_setup(test_db, monkeypatch):
    from apps.api.config import settings
    from apps.api.models.ad_connection import AdConnection
    from apps.api.models.segment import Segment, SegmentMember
    from apps.api.models.site import Site
    from apps.api.models.user import User
    from apps.api.models.visitor import IdentifiedVisitor

    monkeypatch.setattr(settings, "mock_external_apis", True)
    monkeypatch.setattr(settings, "ad_audiences_enabled", True)

    user = User(
        email=f"ads-warn-{uuidlib.uuid4().hex[:8]}@test.com",
        hashed_password="x", full_name="Ads Warn",
    )
    test_db.add(user)
    await test_db.flush()

    site_id = f"ads_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=site_id, user_id=user.id, name="Ads", url="https://ads.example.com"))

    seg_id = uuidlib.uuid4()
    test_db.add(Segment(id=seg_id, site_id=site_id, name="Tiny", visitor_count=3))
    for i in range(3):
        test_db.add(SegmentMember(segment_id=seg_id, visitor_id=f"w{i}", site_id=site_id))
        test_db.add(
            IdentifiedVisitor(
                site_id=site_id, visitor_id=f"w{i}", email=f"w{i}@example.com",
                full_name="First Last", resolution_provider="form_capture",
            )
        )
    test_db.add(
        AdConnection(
            id=uuidlib.uuid4(), site_id=site_id, user_id=user.id, provider="meta",
            auth_type="oauth", status="connected",
        )
    )
    await test_db.commit()
    return {"site_id": site_id, "segment_id": str(seg_id)}


async def test_ads_warning_present_below_minimum(test_db, warning_setup):
    from apps.api.services.ads_push import MIN_AUDIENCE_SIZE, push_segment_to_ads

    outcome = await push_segment_to_ads(
        test_db, warning_setup["site_id"], "meta", warning_setup["segment_id"]
    )
    assert outcome.pushed == 3
    assert outcome.warning, "expected a small-segment warning below the minimum"
    assert "3" in outcome.warning
    assert str(MIN_AUDIENCE_SIZE) in outcome.warning
    # Advisory only — the push still succeeded.
    assert outcome.platform_audience_id


async def test_ads_warning_absent_at_or_above_minimum(test_db, warning_setup, monkeypatch):
    import apps.api.services.ads_push as ads_push

    # Lower the bar rather than seeding 1000 rows — the branch under test is
    # "matched count vs threshold", not the threshold's value.
    monkeypatch.setattr(ads_push, "MIN_AUDIENCE_SIZE", 2)
    outcome = await ads_push.push_segment_to_ads(
        test_db, warning_setup["site_id"], "meta", warning_setup["segment_id"]
    )
    assert outcome.pushed == 3
    assert outcome.warning == ""


async def test_ads_warning_field_is_exposed_on_the_response_schema():
    # The router contract must actually carry the field the UI reads (AC7).
    from apps.api.schemas.ads import PushAdSegmentResult

    assert "warning" in PushAdSegmentResult.model_fields
