"""G7 — GDPR lifecycle for crm_closed_won_contacts (closed-won-lookalikes)."""

import uuid as uuidlib

import pytest
from sqlalchemy import select, text

pytestmark = pytest.mark.integration


async def _site(db):
    from apps.api.models.site import Site
    from apps.api.models.user import User

    user = User(email=f"er-{uuidlib.uuid4().hex[:8]}@test.com", hashed_password="x", full_name="E")
    db.add(user)
    await db.flush()
    site_id = f"er_{uuidlib.uuid4().hex[:8]}"
    db.add(Site(site_id=site_id, user_id=user.id, name="E", url="https://er.example.com"))
    await db.commit()
    return site_id, user


async def _count(db, site_id):
    db.expire_all()
    return (await db.execute(
        text("SELECT count(*) FROM crm_closed_won_contacts WHERE site_id = :s"), {"s": site_id}
    )).scalar_one()


async def test_graph_erasure_sweep_deletes_by_email_bidx(test_db):
    from apps.api.services.closed_won_seed import ingest_deals
    from apps.api.services.crm.base import ClosedWonDeal
    from apps.api.services.graph_erasure import _process_claimed
    from apps.api.services.pii_crypto import email_hash

    site_id, _ = await _site(test_db)
    await ingest_deals(test_db, site_id, [
        ClosedWonDeal("d1", "erase-me@x.example"), ClosedWonDeal("d1", "stay@x.example")
    ], source="crm")
    assert await _count(test_db, site_id) == 2

    from apps.api.models.erasure_request import ErasureRequest

    req = ErasureRequest(requesting_site_id=site_id, visitor_id="v-erase", status="processing",
                         email_bidx_list=[email_hash("erase-me@x.example")], fingerprint_list=None,
                         targets=["beam_identity_graph"])
    test_db.add(req)
    await test_db.commit()
    ok = await _process_claimed(test_db, {
        "id": req.id, "email_bidx_list": [email_hash("erase-me@x.example")],
        "fingerprint_list": [], "targets": ["beam_identity_graph"], "attempts": 1,
    })
    assert ok is True
    assert await _count(test_db, site_id) == 1


async def test_site_delete_removes_contacts_and_sentinel_links(test_db, test_client):
    from apps.api.dependencies import get_current_user
    from apps.api.main import app
    from apps.api.models.ad_audience_link import AdAudienceLink
    from apps.api.models.ad_connection import AdConnection
    from apps.api.services.closed_won_seed import ingest_deals
    from apps.api.services.crm.base import ClosedWonDeal

    site_id, user = await _site(test_db)
    conn = AdConnection(site_id=site_id, user_id=user.id, provider="meta", auth_type="oauth", status="connected")
    test_db.add(conn)
    await test_db.flush()
    test_db.add(AdAudienceLink(connection_id=conn.id, segment_id="closed_won_seed", platform_audience_id="s"))
    test_db.add(AdAudienceLink(connection_id=conn.id, segment_id="closed_won_lookalike:US:0.05",
                               platform_audience_id="l"))
    await test_db.commit()
    await ingest_deals(test_db, site_id, [ClosedWonDeal("d1", "a@x.example")], source="csv")
    conn_id = conn.id

    app.dependency_overrides[get_current_user] = lambda: user
    try:
        r = await test_client.delete(f"/api/v1/sites/{site_id}")
        assert r.status_code in (200, 204), r.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert await _count(test_db, site_id) == 0
    test_db.expire_all()
    left = (await test_db.execute(select(AdAudienceLink).where(AdAudienceLink.connection_id == conn_id))).all()
    assert left == []
