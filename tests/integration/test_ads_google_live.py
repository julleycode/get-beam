"""Phase 3 — Google connect → push → repeat-push, end to end (AC3 + AC6).

"Live" names the code path, NOT the network: every Google call is mocked. The
OAuth callback is driven through the real router handler with a real
oauth_state token and a real DB row; the push then runs with
``mock_external_apis`` OFF and both transports monkeypatched, so the real
two-API sequence (Google Ads userLists:mutate → Data Manager
audienceMembers:ingest) is exercised without a request leaving the process.

G3 specifically: ``platform_audience_id`` must come from the Google Ads
UserList-creation response — never from the Data Manager ingest response, which
carries only an async ``requestId``.

Requires local PostgreSQL + Redis (oauth_state).
"""

import uuid as uuidlib

import pytest
import pytest_asyncio
from sqlalchemy import func, select

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def google_setup(test_db, monkeypatch):
    from apps.api.config import settings
    from apps.api.models.segment import Segment, SegmentMember
    from apps.api.models.site import Site
    from apps.api.models.user import User
    from apps.api.models.visitor import IdentifiedVisitor

    monkeypatch.setattr(settings, "mock_external_apis", True)
    monkeypatch.setattr(settings, "ad_audiences_enabled", True)

    user = User(
        email=f"ads-google-{uuidlib.uuid4().hex[:8]}@test.com",
        hashed_password="x",
        full_name="Ads Google",
    )
    test_db.add(user)
    await test_db.flush()

    site_id = f"ads_google_{uuidlib.uuid4().hex[:8]}"
    test_db.add(
        Site(site_id=site_id, user_id=user.id, name="G", url="https://g.example.com")
    )

    seg_id = uuidlib.uuid4()
    test_db.add(Segment(id=seg_id, site_id=site_id, name="G seg", visitor_count=3))
    # Two US rows survive the EEA filter; the DE row does not.
    for i, country in enumerate(["US", "US", "DE"]):
        test_db.add(SegmentMember(segment_id=seg_id, visitor_id=f"gv{i}", site_id=site_id))
        test_db.add(
            IdentifiedVisitor(
                site_id=site_id,
                visitor_id=f"gv{i}",
                email=f"google{i}@example.com",
                full_name="First Last",
                country=country,
                resolution_provider="form_capture",
            )
        )
    await test_db.commit()
    return {"user": user, "site_id": site_id, "segment_id": str(seg_id)}


async def _connect_via_callback(test_db, google_setup):
    from apps.api.routers import ads as ads_router
    from apps.api.services.oauth_state import store_oauth_state

    user, site_id = google_setup["user"], google_setup["site_id"]
    state = uuidlib.uuid4().hex
    await store_oauth_state(state, f"{user.id}:{site_id}:google")
    return await ads_router.oauth_callback(
        "google", code="fake-auth-code", state=state, db=test_db
    )


def _mock_transports(monkeypatch, created_ids):
    """Swap in the two-API transports; returns the recorded ingest payloads."""
    from apps.api.config import settings
    from apps.api.services.ads.google import GoogleAdsProvider

    monkeypatch.setattr(settings, "mock_external_apis", False)
    monkeypatch.setattr(settings, "google_ads_developer_token", "devtok")

    ingests: list[dict] = []

    async def fake_ads_post(self, url, payload, token):
        rn = f"customers/1234567890/userLists/{created_ids.pop(0)}"
        return {"results": [{"resourceName": rn}]}

    async def fake_dm_post(self, url, payload, token):
        ingests.append(payload)
        # The ingest response NEVER carries an audience id — only a requestId.
        return {"requestId": f"req-{uuidlib.uuid4().hex[:6]}"}

    monkeypatch.setattr(GoogleAdsProvider, "_ads_post", fake_ads_post)
    monkeypatch.setattr(GoogleAdsProvider, "_dm_post", fake_dm_post)
    return ingests


async def test_google_oauth_callback_creates_a_connected_connection(
    test_db, google_setup
):
    """G1 — AC3 automated leg."""
    from apps.api.models.ad_connection import AdConnection

    resp = await _connect_via_callback(test_db, google_setup)
    assert "ads=connected" in str(resp.headers.get("location", ""))

    conn = (
        await test_db.execute(
            select(AdConnection).where(
                AdConnection.site_id == google_setup["site_id"],
                AdConnection.provider == "google",
            )
        )
    ).scalar_one()

    assert conn.status == "connected"
    assert conn.is_valid is True
    assert conn.ad_account_id == "123-456-7890"
    assert conn.last_error is None
    # Both tokens are stored ENCRYPTED — no raw mock value is persisted.
    assert conn.access_token and not conn.access_token.startswith("mock-google-token-")
    assert conn.refresh_token and not conn.refresh_token.startswith("mock-google-refresh-")


async def test_google_push_then_repeat_push_reuses_the_user_list(
    test_db, google_setup, monkeypatch
):
    """G3 — the reused id comes from userLists:mutate, not from the ingest call."""
    from apps.api.models.ad_audience_link import AdAudienceLink
    from apps.api.services.ads_push import push_segment_to_ads

    await _connect_via_callback(test_db, google_setup)
    site_id, segment_id = google_setup["site_id"], google_setup["segment_id"]

    # A second id is queued so a wrongly-repeated create would be detectable.
    ingests = _mock_transports(monkeypatch, ["555", "666"])

    first = await push_segment_to_ads(test_db, site_id, "google", segment_id)
    assert first.found is True
    assert first.platform_audience_id == "customers/1234567890/userLists/555"
    # The DE visitor was filtered out before hashing.
    assert first.pushed == 2
    assert first.skipped == 1

    second = await push_segment_to_ads(test_db, site_id, "google", segment_id)
    assert second.platform_audience_id == first.platform_audience_id, (
        "repeat push created a NEW user list instead of reusing the link row"
    )
    assert "req-" not in second.platform_audience_id, (
        "audience id was sourced from the Data Manager requestId"
    )

    link_count = await test_db.scalar(
        select(func.count())
        .select_from(AdAudienceLink)
        .where(AdAudienceLink.segment_id == segment_id)
    )
    assert link_count == 1

    # Both pushes ingested against the same user list id, with consent + ToS.
    assert len(ingests) == 2
    for payload in ingests:
        assert payload["destinations"][0]["productDestinationId"] == "555"
        assert payload["consent"]["adUserData"] == "CONSENT_GRANTED"
        assert (
            payload["termsOfService"]["customerMatchTermsOfServiceStatus"] == "ACCEPTED"
        )


async def test_google_push_excludes_eea_rows_end_to_end(
    test_db, google_setup, monkeypatch
):
    """G4 integration leg — no EEA digest reaches the ingest payload."""
    from apps.api.services.ads_push import push_segment_to_ads
    from apps.api.services.csv_exporter import _sha256

    await _connect_via_callback(test_db, google_setup)
    ingests = _mock_transports(monkeypatch, ["777"])

    await push_segment_to_ads(
        test_db, google_setup["site_id"], "google", google_setup["segment_id"]
    )

    sent = {
        m["userData"]["userIdentifiers"][0]["emailAddress"]
        for m in ingests[0]["audienceMembers"]
    }
    assert _sha256("google2@example.com") not in sent, "EEA visitor was uploaded"
    assert _sha256("google0@example.com") in sent
    assert len(sent) == 2
