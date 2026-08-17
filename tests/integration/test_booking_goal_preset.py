"""AC-1 / AC-5 / AC-6 — booking_url persistence and the "Demo booked" goal preset.

AC-1: booking_url round-trips through PATCH/GET /sites/{site_id}.
AC-5: the preset body creates an ordinary url_match ConversionGoal via the
      EXISTING POST /{site_id}/goals, and conversion_tracker.matches_goal matches
      a landing path under it. A full https:// pattern is REJECTED.
AC-6: saving booking_url creates zero ConversionGoal rows.

Requires: PostgreSQL AND Redis running locally (via docker-compose).
"""

import uuid as uuidlib

import pytest
import pytest_asyncio
from sqlalchemy import func, select

pytestmark = pytest.mark.integration

_BOOKING_URL = "https://cal.com/acme/demo"


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "Booking Tester"},
    )
    if resp.status_code != 200:
        resp = await test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "testpass123"}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def booking_setup(test_client, test_db):
    from apps.api.models.site import Site
    from apps.api.models.user import User

    email = f"booking-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()

    site_id = f"booking_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(
        Site(
            site_id=site_id,
            user_id=user.id,
            name="Booking Site",
            url="https://b.example.com",
        )
    )
    await test_db.commit()
    return {"token": token, "site_id": site_id}


class TestBookingUrlPersistence:
    @pytest.mark.asyncio
    async def test_booking_url_round_trips(self, test_client, booking_setup):
        """AC-1 — PATCH a REAL non-null value and re-GET it (a null-only
        assertion would be vacuous)."""
        sid, token = booking_setup["site_id"], booking_setup["token"]

        resp = await test_client.get(f"/api/v1/sites/{sid}", headers=_auth(token))
        assert resp.status_code == 200, resp.text
        assert resp.json()["booking_url"] is None

        resp = await test_client.patch(
            f"/api/v1/sites/{sid}",
            headers=_auth(token),
            json={"booking_url": _BOOKING_URL},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["booking_url"] == _BOOKING_URL

        resp = await test_client.get(f"/api/v1/sites/{sid}", headers=_auth(token))
        assert resp.json()["booking_url"] == _BOOKING_URL

    @pytest.mark.asyncio
    async def test_hostile_booking_url_rejected_at_api(self, test_client, booking_setup):
        """AC-10 at the API boundary, not just the schema unit."""
        sid, token = booking_setup["site_id"], booking_setup["token"]
        resp = await test_client.patch(
            f"/api/v1/sites/{sid}",
            headers=_auth(token),
            json={"booking_url": "javascript:alert(1)"},
        )
        assert resp.status_code == 422, resp.text

    @pytest.mark.asyncio
    async def test_other_user_cannot_set_booking_url(self, test_client, booking_setup):
        other = await _signup(test_client, f"other-{uuidlib.uuid4().hex[:8]}@test.com")
        resp = await test_client.patch(
            f"/api/v1/sites/{booking_setup['site_id']}",
            headers=_auth(other),
            json={"booking_url": _BOOKING_URL},
        )
        assert resp.status_code == 404


class TestNoAutoGoalCreation:
    @pytest.mark.asyncio
    async def test_saving_booking_url_creates_no_goal(
        self, test_client, test_db, booking_setup
    ):
        """AC-6 — silently creating a conversion goal would change a site's
        reported metrics without consent."""
        from apps.api.models.outcome import ConversionGoal

        sid, token = booking_setup["site_id"], booking_setup["token"]

        async def _goal_count() -> int:
            return (
                await test_db.execute(
                    select(func.count())
                    .select_from(ConversionGoal)
                    .where(ConversionGoal.site_id == sid)
                )
            ).scalar_one()

        before = await _goal_count()
        resp = await test_client.patch(
            f"/api/v1/sites/{sid}",
            headers=_auth(token),
            json={"booking_url": _BOOKING_URL},
        )
        assert resp.status_code == 200, resp.text
        assert await _goal_count() == before == 0


class TestDemoBookedGoalPreset:
    @pytest.mark.asyncio
    async def test_preset_body_creates_goal_and_matches_landing_path(
        self, test_client, booking_setup
    ):
        """AC-5 — the preset posts to the EXISTING goals endpoint unchanged."""
        from apps.api.services.conversion_tracker import matches_goal

        sid, token = booking_setup["site_id"], booking_setup["token"]

        resp = await test_client.post(
            f"/api/v1/outcomes/{sid}/goals",
            headers=_auth(token),
            json={
                "name": "Demo booked",
                "goal_type": "url_match",
                "match_type": "prefix",
                "pattern": "/thanks",
            },
        )
        assert resp.status_code == 200, resp.text
        goal = resp.json()
        assert goal["goal_type"] == "url_match"
        assert goal["match_type"] == "prefix"
        assert goal["pattern"] == "/thanks"

        # The stored rule matches the customer's thank-you landing path.
        # matches_goal(pattern, match_type, path)
        assert matches_goal("/thanks", "prefix", "/thanks/demo") is True
        assert matches_goal("/thanks", "prefix", "/pricing") is False

    @pytest.mark.asyncio
    async def test_full_url_pattern_is_rejected(self, test_client, booking_setup):
        """matches_goal compares a NORMALIZED PATH, so a full URL is both
        rejected at create time and unmatchable if it somehow persisted."""
        sid, token = booking_setup["site_id"], booking_setup["token"]
        resp = await test_client.post(
            f"/api/v1/outcomes/{sid}/goals",
            headers=_auth(token),
            json={
                "name": "Demo booked full url",
                "goal_type": "url_match",
                "match_type": "prefix",
                "pattern": "https://acme.com/thanks",
            },
        )
        assert resp.status_code == 422, resp.text
