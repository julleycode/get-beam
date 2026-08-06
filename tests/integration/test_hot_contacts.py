"""Integration tests for identity-honesty Phase 6 — hot imported contacts.

Covers SPEC AC13 (the "N of your M imported contacts active this week" count is
correct against real rows, including a phantom with TWO merged children counted
exactly once) and the umbrella's cross-tenant hard safety constraint (another
site's imported contacts never leak into this site's N/M or drill-down list).

Test names are keyword-selectable to match the validate-contract gates:
``-k count`` → the N/M arithmetic; ``-k tenant`` → the isolation gate.

Requires: PostgreSQL running locally (via docker-compose). Docker-gated
known-gap in the current sandbox, same class as Phases 1/4/5.
"""

import uuid as uuidlib
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration

NOW = datetime.utcnow()
RECENT = NOW - timedelta(days=2)
STALE = NOW - timedelta(days=30)


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "Hot Tester"},
    )
    if resp.status_code != 200:
        resp = await test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "testpass123"}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _make_site(test_client, test_db, prefix: str) -> tuple[str, str]:
    from apps.api.models.site import Site
    from apps.api.models.user import User

    email = f"{prefix}-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()
    site_id = f"{prefix}_{uuidlib.uuid4().hex[:8]}"
    test_db.add(
        Site(site_id=site_id, user_id=user.id, name="Hot Site", url="https://h.example.com")
    )
    await test_db.commit()
    return token, site_id


async def _phantom(test_db, site_id: str, visitor_id: str, email: str, name: str):
    """An imported contact exactly as contact_importer creates it: no traffic."""
    from apps.api.models.visitor import IdentifiedVisitor, Visitor

    test_db.add(
        Visitor(
            site_id=site_id,
            visitor_id=visitor_id,
            first_seen=NOW,
            # Frozen at import time and NEVER updated by a later visit — the
            # whole reason the query must resolve the merged-child pointer.
            last_seen=NOW,
            total_pageviews=0,
            identity_status="identified",
            is_imported_contact=True,
        )
    )
    test_db.add(
        IdentifiedVisitor(
            site_id=site_id,
            visitor_id=visitor_id,
            email=email,
            full_name=name,
            resolution_provider="contact_import",
        )
    )
    await test_db.commit()


async def _merged_child(test_db, site_id: str, child_id: str, phantom_id: str, last_seen):
    """A real click-derived visit that later merged onto the phantom."""
    from apps.api.models.visitor import Visitor

    test_db.add(
        Visitor(
            site_id=site_id,
            visitor_id=child_id,
            first_seen=last_seen,
            last_seen=last_seen,
            total_pageviews=4,
            identity_status="merged",
            canonical_visitor_id=phantom_id,
        )
    )
    await test_db.commit()


@pytest_asyncio.fixture
async def hot_site(test_client, test_db):
    token, site_id = await _make_site(test_client, test_db, "hot")
    return {"token": token, "site_id": site_id}


class TestHotContactsCount:
    """AC13 — the N/M arithmetic (``-k count``)."""

    @pytest.mark.asyncio
    async def test_count_active_versus_total(self, test_client, test_db, hot_site):
        site_id = hot_site["site_id"]
        # 3 imported contacts: one recently active, one active long ago, one
        # never visited at all.
        await _phantom(test_db, site_id, "import:a", "a@ex.com", "Active Ann")
        await _merged_child(test_db, site_id, "click:a", "import:a", RECENT)
        await _phantom(test_db, site_id, "import:b", "b@ex.com", "Stale Sam")
        await _merged_child(test_db, site_id, "click:b", "import:b", STALE)
        await _phantom(test_db, site_id, "import:c", "c@ex.com", "Never Ned")

        resp = await test_client.get(
            f"/api/v1/sites/{site_id}/contacts/hot", headers=_auth(hot_site["token"])
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total_count"] == 3, "M counts every imported contact"
        assert body["active_count"] == 1, "only the recently-active phantom is N"
        assert [c["email"] for c in body["contacts"]] == ["a@ex.com"]

    @pytest.mark.asyncio
    async def test_count_multi_merged_child_phantom_exactly_once(
        self, test_client, test_db, hot_site
    ):
        """The double-count bug: one contact, two devices, two merged children.

        Both children point at the SAME phantom. A plain LEFT JOIN + COUNT(*)
        reports 2; the correct answer is 1, using the most recent activity.
        """
        site_id = hot_site["site_id"]
        await _phantom(test_db, site_id, "import:multi", "multi@ex.com", "Multi Mo")
        await _merged_child(test_db, site_id, "click:laptop", "import:multi", RECENT)
        await _merged_child(test_db, site_id, "click:phone", "import:multi", STALE)

        resp = await test_client.get(
            f"/api/v1/sites/{site_id}/contacts/hot", headers=_auth(hot_site["token"])
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total_count"] == 1
        assert body["active_count"] == 1, "a 2-merged-child phantom must count ONCE"
        assert len(body["contacts"]) == 1, "and must appear once in the drill-down"
        # The reported activity is the MOST RECENT of the two children.
        reported = datetime.fromisoformat(body["contacts"][0]["last_activity_at"])
        assert abs((reported - RECENT).total_seconds()) < 2

    @pytest.mark.asyncio
    async def test_count_ignores_non_imported_visitors(
        self, test_client, test_db, hot_site
    ):
        """Ordinary traffic never inflates M or N."""
        from apps.api.models.visitor import Visitor

        site_id = hot_site["site_id"]
        test_db.add(
            Visitor(
                site_id=site_id,
                visitor_id="organic:1",
                first_seen=RECENT,
                last_seen=RECENT,
                total_pageviews=9,
                identity_status="identified",
            )
        )
        await test_db.commit()

        resp = await test_client.get(
            f"/api/v1/sites/{site_id}/contacts/hot", headers=_auth(hot_site["token"])
        )
        assert resp.json() == {
            "active_count": 0,
            "total_count": 0,
            "window_days": 7,
            "contacts": [],
        }


class TestHotContactsTenantIsolation:
    """Umbrella hard safety constraint (``-k tenant``)."""

    @pytest.mark.asyncio
    async def test_other_tenants_contacts_never_appear(
        self, test_client, test_db, hot_site
    ):
        mine = hot_site["site_id"]
        other_token, other_site = await _make_site(test_client, test_db, "hot2")

        await _phantom(test_db, mine, "import:mine", "mine@ex.com", "Mine")
        await _merged_child(test_db, mine, "click:mine", "import:mine", RECENT)
        # Two active imported contacts on the OTHER tenant's site.
        await _phantom(test_db, other_site, "import:theirs1", "t1@ex.com", "Theirs One")
        await _merged_child(test_db, other_site, "click:t1", "import:theirs1", RECENT)
        await _phantom(test_db, other_site, "import:theirs2", "t2@ex.com", "Theirs Two")
        await _merged_child(test_db, other_site, "click:t2", "import:theirs2", RECENT)

        resp = await test_client.get(
            f"/api/v1/sites/{mine}/contacts/hot", headers=_auth(hot_site["token"])
        )
        body = resp.json()
        assert body["total_count"] == 1 and body["active_count"] == 1
        emails = [c["email"] for c in body["contacts"]]
        assert emails == ["mine@ex.com"]
        assert "t1@ex.com" not in emails and "t2@ex.com" not in emails

        # And the other tenant sees exactly their own two.
        other = await test_client.get(
            f"/api/v1/sites/{other_site}/contacts/hot", headers=_auth(other_token)
        )
        assert other.json()["active_count"] == 2

    @pytest.mark.asyncio
    async def test_foreign_site_id_returns_404_not_403(
        self, test_client, test_db, hot_site
    ):
        """404, never 403 — never leak which site_ids exist."""
        _, other_site = await _make_site(test_client, test_db, "hot3")
        resp = await test_client.get(
            f"/api/v1/sites/{other_site}/contacts/hot", headers=_auth(hot_site["token"])
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_hot_route_is_not_shadowed_by_contact_detail_route(
        self, test_client, test_db, hot_site
    ):
        """Live proof that /contacts/hot reaches the hot endpoint, not /{visitor_id}.

        Against the shadowed registration order this returns 404 ("Contact not
        found" from get_imported_contact with visitor_id="hot").
        """
        resp = await test_client.get(
            f"/api/v1/sites/{hot_site['site_id']}/contacts/hot",
            headers=_auth(hot_site["token"]),
        )
        assert resp.status_code == 200
        assert "active_count" in resp.json(), "resolved to the by-id endpoint instead"
