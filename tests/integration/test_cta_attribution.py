"""AC4 / AC5 / AC6 — structured CTA config, per-type click attribution, counts.

Flag ON (cta_types_enabled) against real Postgres. Requires PG + Redis
(docker-compose) with DATABASE_URL pinned to localhost.
"""

import uuid as uuidlib

import pytest
import pytest_asyncio
from sqlalchemy import func, select

pytestmark = pytest.mark.integration

_SITE_URL = "https://shop.example.com"
_BOOKING = "https://cal.com/acme/demo"
_TRIAL = "https://shop.example.com/trial"


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "CTA Tester"},
    )
    if resp.status_code != 200:
        resp = await test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "testpass123"}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    from apps.api.config import settings

    monkeypatch.setattr(settings, "cta_types_enabled", True)


@pytest_asyncio.fixture
async def cta_setup(test_client, test_db):
    from apps.api.models.site import Site
    from apps.api.models.user import User

    email = f"cta-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()
    site_id = f"cta_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=site_id, user_id=user.id, name="CTA Site", url=_SITE_URL))
    await test_db.commit()
    return {"token": token, "site_id": site_id}


async def _configure(test_client, setup) -> None:
    resp = await test_client.patch(
        f"/api/v1/sites/{setup['site_id']}",
        headers=_auth(setup["token"]),
        json={
            "booking_url": _BOOKING,
            "cta_config": {
                "default": "free_trial",
                "types": {"free_trial": {"url": _TRIAL, "label": "Start trial"}},
            },
        },
    )
    assert resp.status_code == 200, resp.text


async def _click_count(test_db, site_id: str, cta_type: str) -> int:
    from apps.api.models.cta_click_event import CtaClickEvent

    return (
        await test_db.execute(
            select(func.count()).select_from(CtaClickEvent).where(
                CtaClickEvent.site_id == site_id, CtaClickEvent.cta_type == cta_type
            )
        )
    ).scalar_one()


class TestCtaConfigCrud:
    @pytest.mark.asyncio
    async def test_round_trips(self, test_client, cta_setup):
        await _configure(test_client, cta_setup)
        resp = await test_client.get(
            f"/api/v1/sites/{cta_setup['site_id']}", headers=_auth(cta_setup["token"])
        )
        assert resp.status_code == 200, resp.text
        cfg = resp.json()["cta_config"]
        assert cfg["default"] == "free_trial"
        assert cfg["types"]["free_trial"]["url"] == _TRIAL

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "cfg",
        [
            {"types": {"free_trial": {"url": "https://evil.com/trial"}}},  # foreign host
            {"types": {"free_trial": {"url": "http://shop.example.com/t"}}},  # not https
            {"types": {"book_demo": {"url": "https://cal.com/x"}}},  # book_demo uses booking_url
            {"types": {"resource": {"url": "https://shop.example.com/<x>"}}},  # injection
            {"default": "bogus"},
        ],
    )
    async def test_url_rule_rejects(self, test_client, cta_setup, cfg):
        resp = await test_client.patch(
            f"/api/v1/sites/{cta_setup['site_id']}",
            headers=_auth(cta_setup["token"]),
            json={"cta_config": cfg},
        )
        assert resp.status_code == 422, resp.text

    @pytest.mark.asyncio
    async def test_foreign_site_404(self, test_client, cta_setup):
        other = await _signup(test_client, f"cta-o-{uuidlib.uuid4().hex[:8]}@test.com")
        resp = await test_client.patch(
            f"/api/v1/sites/{cta_setup['site_id']}",
            headers=_auth(other),
            json={"cta_config": {"default": "reply"}},
        )
        assert resp.status_code == 404
        resp = await test_client.get(
            f"/api/v1/campaigns/{cta_setup['site_id']}/cta-clicks", headers=_auth(other)
        )
        assert resp.status_code == 404


class TestCtaClicks:
    @pytest.mark.asyncio
    async def test_row_per_hit_with_and_without_t(self, test_client, test_db, cta_setup):
        from apps.api.services.link_decorator import generate_bid

        await _configure(test_client, cta_setup)
        sid = cta_setup["site_id"]
        for params in (
            {"ct": "free_trial"},
            {"ct": "free_trial"},
            {"ct": "free_trial", "t": generate_bid("buyer@shop.com")},
        ):
            resp = await test_client.get(f"/c/{sid}", params=params, follow_redirects=False)
            assert resp.status_code == 302
            assert resp.headers["location"].startswith(_TRIAL)
        assert await _click_count(test_db, sid, "free_trial") == 3

        resp = await test_client.get(
            f"/c/{sid}", params={"ct": "book_demo", "u": "https://evil.com"},
            follow_redirects=False,
        )
        assert resp.headers["location"] == _BOOKING

    @pytest.mark.asyncio
    async def test_tp_stamps_clicked_at_and_appends_bid_tp(self, test_client, test_db, cta_setup):
        from apps.api.models.campaign import Campaign, CampaignTouchpoint
        from apps.api.services.link_decorator import generate_bid

        await _configure(test_client, cta_setup)
        sid = cta_setup["site_id"]
        camp = Campaign(site_id=sid, name="c", status="active", plan={})
        test_db.add(camp)
        await test_db.flush()
        tp = CampaignTouchpoint(
            campaign_id=camp.id, visitor_id="v1", channel="email",
            touchpoint_order=1, status="sent", content={},
        )
        test_db.add(tp)
        await test_db.commit()

        resp = await test_client.get(
            f"/c/{sid}",
            params={"ct": "free_trial", "tp": str(tp.id), "cid": str(camp.id),
                    "t": generate_bid("buyer@shop.com")},
            follow_redirects=False,
        )
        loc = resp.headers["location"]
        assert loc.startswith(_TRIAL + "?_bid=")
        assert f"&_tp={tp.id}" in loc
        await test_db.refresh(tp)
        assert tp.clicked_at is not None

    @pytest.mark.asyncio
    async def test_foreign_site_tp_ignored(self, test_client, test_db, cta_setup):
        from apps.api.models.campaign import Campaign, CampaignTouchpoint
        from apps.api.models.site import Site

        await _configure(test_client, cta_setup)
        other_sid = f"cta_other_{uuidlib.uuid4().hex[:8]}"
        owner_id = (
            await test_db.execute(
                select(Site.user_id).where(Site.site_id == cta_setup["site_id"])
            )
        ).scalar_one()
        test_db.add(
            Site(site_id=other_sid, user_id=owner_id, name="Other", url="https://other.example")
        )
        await test_db.flush()
        camp = Campaign(site_id=other_sid, name="c", status="active", plan={})
        test_db.add(camp)
        await test_db.flush()
        tp = CampaignTouchpoint(
            campaign_id=camp.id, visitor_id="v1", channel="email",
            touchpoint_order=1, status="sent", content={},
        )
        test_db.add(tp)
        await test_db.commit()

        resp = await test_client.get(
            f"/c/{cta_setup['site_id']}",
            params={"ct": "free_trial", "tp": str(tp.id)},
            follow_redirects=False,
        )
        assert resp.headers["location"] == _TRIAL
        await test_db.refresh(tp)
        assert tp.clicked_at is None

    @pytest.mark.asyncio
    async def test_counts_endpoint_reachable_not_shadowed(self, test_client, cta_setup):
        await _configure(test_client, cta_setup)
        sid = cta_setup["site_id"]
        await test_client.get(f"/c/{sid}", params={"ct": "free_trial"}, follow_redirects=False)
        await test_client.get(f"/c/{sid}", params={"ct": "reply"}, follow_redirects=False)
        resp = await test_client.get(
            f"/api/v1/campaigns/{sid}/cta-clicks", headers=_auth(cta_setup["token"])
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"counts": {"free_trial": 1, "reply": 1}}
