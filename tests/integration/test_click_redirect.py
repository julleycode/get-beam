"""Own-data P7c: email click-tracking redirect endpoint (GET /c/{site_id}).

A recipient click binds their email to a Beam visitor and 302s to the destination.
"""
import uuid as uuidlib

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration

_BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"


@pytest_asyncio.fixture
async def click_site(test_db):
    from apps.api.models.site import Site
    from apps.api.models.user import User

    email = f"click-{uuidlib.uuid4().hex[:8]}@test.com"
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if not user:
        user = User(email=email, full_name="Click Tester")
        test_db.add(user)
        await test_db.flush()
    site_id = f"click_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=site_id, user_id=user.id, name="Click Site", url="https://shop.example.com"))
    await test_db.commit()
    return site_id


def _token(email: str) -> str:
    from apps.api.services.link_decorator import generate_bid
    return generate_bid(email)


class TestClickRedirect:
    @pytest.mark.asyncio
    async def test_click_binds_email_and_redirects(self, test_client, click_site, test_db):
        from apps.api.models.visitor_email import VisitorEmail

        resp = await test_client.get(
            f"/c/{click_site}",
            params={"t": _token("Buyer@Shop.com"), "u": "https://shop.example.com/product/42"},
            headers={"User-Agent": _BROWSER_UA},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "https://shop.example.com/product/42"
        # svid cookie set so a later pixel visit reconciles this person (P1).
        assert any("_rta_svid_" in c for c in resp.headers.get_list("set-cookie"))

        row = (
            await test_db.execute(
                select(VisitorEmail).where(
                    VisitorEmail.site_id == click_site, VisitorEmail.email == "buyer@shop.com"
                )
            )
        ).scalar_one()
        assert row.source == "email_click"

    @pytest.mark.asyncio
    async def test_foreign_destination_redirects_to_homepage(self, test_client, click_site):
        # Open-redirect guard: a foreign `u` must never be honored.
        resp = await test_client.get(
            f"/c/{click_site}",
            params={"t": _token("x@shop.com"), "u": "https://evil.com/phish"},
            headers={"User-Agent": _BROWSER_UA},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "https://shop.example.com"

    @pytest.mark.asyncio
    async def test_replayed_token_does_not_bloat(self, test_client, click_site, test_db):
        # A forwarded link clicked repeatedly (cookieless) must dedupe to ONE row.
        from sqlalchemy import func

        from apps.api.models.visitor_email import VisitorEmail

        tok = _token("replay@shop.com")
        for _ in range(3):
            r = await test_client.get(
                f"/c/{click_site}",
                params={"t": tok, "u": "https://shop.example.com/x"},
                headers={"User-Agent": _BROWSER_UA, "cookie": ""},
                follow_redirects=False,
            )
            assert r.status_code == 302
        n = (
            await test_db.execute(
                select(func.count()).select_from(VisitorEmail).where(
                    VisitorEmail.site_id == click_site, VisitorEmail.email == "replay@shop.com"
                )
            )
        ).scalar()
        assert n == 1

    @pytest.mark.asyncio
    async def test_unknown_site_404(self, test_client):
        resp = await test_client.get(
            "/c/no_such_site",
            params={"t": _token("x@y.com"), "u": "https://x.com"},
            headers={"User-Agent": _BROWSER_UA},
            follow_redirects=False,
        )
        assert resp.status_code == 404
