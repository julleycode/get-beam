"""AC4 — the ad push honours the exact same safety-filter chain as CSV export.

Seeds a segment with four visitor classes and asserts only the emailable,
non-suppressed, non-agent-derived subset reaches the outbound payload. The
filter itself is csv_exporter._get_segment_visitors, imported (never copied) by
services/ads_push.py — this test proves the import is actually wired.

Requires local PostgreSQL. Runs 100% in mock mode.
"""

import uuid as uuidlib

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def safety_setup(test_db, monkeypatch):
    from apps.api.config import settings
    from apps.api.models.segment import Segment, SegmentMember
    from apps.api.models.site import Site
    from apps.api.models.user import User
    from apps.api.models.visitor import IdentifiedVisitor
    from apps.api.services.suppression import add_suppression

    monkeypatch.setattr(settings, "mock_external_apis", True)
    monkeypatch.setattr(settings, "ad_audiences_enabled", True)

    user = User(
        email=f"ads-safety-{uuidlib.uuid4().hex[:8]}@test.com",
        hashed_password="x",
        full_name="Ads Safety",
    )
    test_db.add(user)
    await test_db.flush()

    site_id = f"ads_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=site_id, user_id=user.id, name="Ads", url="https://ads.example.com"))

    seg_id = uuidlib.uuid4()
    test_db.add(Segment(id=seg_id, site_id=site_id, name="Safety", visitor_count=4))

    # 4 classes: A emailable, B do_not_email, C agent-derived, D do_not_sell.
    rows = [
        ("vA", "keep-me@example.com", dict(resolution_provider="form_capture")),
        ("vB", "bounced@example.com", dict(resolution_provider="form_capture", do_not_email=True)),
        ("vC", "agent@example.com", dict(resolution_provider="form_capture",
                                         source_agent_visit_id=str(uuidlib.uuid4()))),
        ("vD", "donotsell@example.com", dict(resolution_provider="form_capture")),
    ]
    for visitor_id, email, extra in rows:
        test_db.add(SegmentMember(segment_id=seg_id, visitor_id=visitor_id, site_id=site_id))
        test_db.add(
            IdentifiedVisitor(
                site_id=site_id, visitor_id=visitor_id, email=email,
                full_name="First Last", **extra,
            )
        )
    await test_db.commit()
    await add_suppression(test_db, "donotsell@example.com", "do_not_sell")

    return {"user": user, "site_id": site_id, "segment_id": str(seg_id)}


async def test_ads_safety_filter_only_pushes_cleared_contacts(test_db, safety_setup):
    from apps.api.models.ad_connection import AdConnection
    from apps.api.services.ads_push import build_hashed_contacts, push_segment_to_ads
    from apps.api.services.csv_exporter import _get_segment_visitors, _sha256

    site_id = safety_setup["site_id"]
    segment_id = safety_setup["segment_id"]

    test_db.add(
        AdConnection(
            id=uuidlib.uuid4(), site_id=site_id, user_id=safety_setup["user"].id,
            provider="meta", auth_type="oauth", status="connected",
        )
    )
    await test_db.commit()

    # What the shared filter chain returns is what the payload builder gets.
    rows = await _get_segment_visitors(test_db, segment_id, exclude_known=False)
    emails = {r["email"] for r in rows}
    assert emails == {"keep-me@example.com"}, f"safety chain let through {emails}"

    payload = build_hashed_contacts(rows)
    assert len(payload) == 1
    assert payload[0].email_sha256 == _sha256("keep-me@example.com")
    # The three excluded people are not in the payload under any hashing.
    excluded = {_sha256(e) for e in
                ("bounced@example.com", "agent@example.com", "donotsell@example.com")}
    assert not ({c.email_sha256 for c in payload} & excluded)

    outcome = await push_segment_to_ads(test_db, site_id, "meta", segment_id)
    assert outcome.found is True
    assert outcome.pushed == 1
    # 4 members in, 1 pushed → 3 filtered out by the safety chain.
    assert outcome.skipped == 3


async def test_ads_safety_filter_missing_connection_is_not_found(test_db, safety_setup):
    from apps.api.services.ads_push import push_segment_to_ads

    outcome = await push_segment_to_ads(
        test_db, safety_setup["site_id"], "google", safety_setup["segment_id"]
    )
    assert outcome.found is False
    assert outcome.pushed == 0
