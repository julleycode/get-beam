"""Integration tests for identity-honesty Phase 4 — CSV contact import.

Covers SPEC AC9 (import → list → detail, and the 5,000/site cap boundary),
AC10 (each imported contact gets a working tokenized link), AC18 (cross-tenant
isolation), and the D8 behavioural proof of the phantom-exclusion predicate
(excluded while unvisited, re-included once a merged child row exists).

Requires: PostgreSQL running locally (via docker-compose).
"""

import io
import uuid as uuidlib
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration

CAP = 5_000


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "Import Tester"},
    )
    if resp.status_code != 200:
        resp = await test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "testpass123"}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _csv(rows: list[tuple[str, str]]) -> dict:
    body = "".join(f"{name},{email}\n" for name, email in rows)
    return {"file": ("contacts.csv", io.BytesIO(body.encode()), "text/csv")}


async def _make_site(test_client, test_db, prefix: str) -> tuple[str, str]:
    from apps.api.models.site import Site
    from apps.api.models.user import User

    email = f"{prefix}-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()
    site_id = f"{prefix}_{uuidlib.uuid4().hex[:8]}"
    test_db.add(
        Site(site_id=site_id, user_id=user.id, name="Import Site", url="https://i.example.com")
    )
    await test_db.commit()
    return token, site_id


@pytest_asyncio.fixture
async def import_site(test_client, test_db):
    token, site_id = await _make_site(test_client, test_db, "imp")
    return {"token": token, "site_id": site_id}


class TestImportFlow:
    @pytest.mark.asyncio
    async def test_import_then_list_then_detail(self, test_client, test_db, import_site):
        """AC9: import creates phantom Visitor rows, listable and detailable."""
        from apps.api.models.visitor import Visitor

        site_id, token = import_site["site_id"], import_site["token"]
        resp = await test_client.post(
            f"/api/v1/sites/{site_id}/contacts/import",
            headers=_auth(token),
            files=_csv([("Ada Lovelace", "ada@example.com"), ("Grace H", "grace@example.com")]),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["imported"] == 2

        rows = (
            await test_db.execute(
                select(Visitor).where(
                    Visitor.site_id == site_id, Visitor.is_imported_contact.is_(True)
                )
            )
        ).scalars().all()
        assert len(rows) == 2
        assert all(v.visitor_id.startswith("import:") for v in rows)
        assert all(v.identity_status == "identified" for v in rows)

        listing = await test_client.get(
            f"/api/v1/sites/{site_id}/contacts", headers=_auth(token)
        )
        assert listing.status_code == 200
        assert listing.json()["total"] == 2

        vid = rows[0].visitor_id
        detail = await test_client.get(
            f"/api/v1/sites/{site_id}/contacts/{vid}", headers=_auth(token)
        )
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["email"] in {"ada@example.com", "grace@example.com"}
        # AC10: a working tokenized link, produced by the existing _bid mechanism.
        assert body["tracking_link"] and "_bid=" in body["tracking_link"]

    @pytest.mark.asyncio
    async def test_malformed_rows_are_rejected_not_persisted(
        self, test_client, test_db, import_site
    ):
        """B1a: garbage never reaches IdentifiedVisitor.email."""
        site_id, token = import_site["site_id"], import_site["token"]
        resp = await test_client.post(
            f"/api/v1/sites/{site_id}/contacts/import",
            headers=_auth(token),
            files=_csv([("Good", "good@example.com"), ("Bad", "not-an-email")]),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["imported"] == 1
        assert resp.json()["rejected"] == 1


class TestQuotaBoundary:
    @pytest.mark.asyncio
    async def test_exactly_at_cap_succeeds_and_one_over_is_rejected_whole(
        self, test_client, test_db, import_site
    ):
        """AC9: 5,000 succeeds; 5,001 rejected with a clear error, no partial import."""
        from apps.api.models.visitor import Visitor

        site_id, token = import_site["site_id"], import_site["token"]
        at_cap = [(f"P{i}", f"p{i}@example.com") for i in range(CAP)]
        resp = await test_client.post(
            f"/api/v1/sites/{site_id}/contacts/import",
            headers=_auth(token),
            files=_csv(at_cap),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["imported"] == CAP

        over = await test_client.post(
            f"/api/v1/sites/{site_id}/contacts/import",
            headers=_auth(token),
            files=_csv([("One More", "onemore@example.com")]),
        )
        assert over.status_code == 400
        assert str(CAP) in over.json()["detail"]

        count = (
            await test_db.execute(
                select(Visitor).where(
                    Visitor.site_id == site_id, Visitor.is_imported_contact.is_(True)
                )
            )
        ).scalars().all()
        assert len(count) == CAP, "rejection must be whole-file — never a partial import"


class TestCrossTenantIsolation:
    @pytest.mark.asyncio
    async def test_site_b_cannot_see_or_import_into_site_a(
        self, test_client, test_db, import_site
    ):
        """AC18: an imported contact from site A is invisible from site B."""
        site_a, token_a = import_site["site_id"], import_site["token"]
        await test_client.post(
            f"/api/v1/sites/{site_a}/contacts/import",
            headers=_auth(token_a),
            files=_csv([("Ada", "ada-iso@example.com")]),
        )
        token_b, _site_b = await _make_site(test_client, test_db, "impb")

        # 404 (not 403) — never leak which site_ids exist.
        assert (
            await test_client.get(
                f"/api/v1/sites/{site_a}/contacts", headers=_auth(token_b)
            )
        ).status_code == 404
        assert (
            await test_client.post(
                f"/api/v1/sites/{site_a}/contacts/import",
                headers=_auth(token_b),
                files=_csv([("Mallory", "mallory@example.com")]),
            )
        ).status_code == 404


class TestPhantomExclusionPredicate:
    """D8 behavioural proof of the corrected EXISTS-subquery predicate."""

    @pytest.mark.asyncio
    async def test_unvisited_phantom_excluded_then_included_once_merged(
        self, test_client, test_db, import_site
    ):
        from apps.api.models.visitor import Visitor
        from apps.api.services.agent_visitor_filters import human_only_visitor_filter

        site_id, token = import_site["site_id"], import_site["token"]
        await test_client.post(
            f"/api/v1/sites/{site_id}/contacts/import",
            headers=_auth(token),
            files=_csv([("Ada", "ada-pred@example.com")]),
        )
        phantom = (
            await test_db.execute(
                select(Visitor).where(
                    Visitor.site_id == site_id, Visitor.is_imported_contact.is_(True)
                )
            )
        ).scalar_one()

        async def _visible() -> list[str]:
            rows = (
                await test_db.execute(
                    select(Visitor.visitor_id).where(
                        Visitor.site_id == site_id, human_only_visitor_filter()
                    )
                )
            ).scalars().all()
            return list(rows)

        assert phantom.visitor_id not in await _visible(), (
            "an unvisited phantom must be excluded from human rollups"
        )

        # A real visit arrives and merges onto the phantom (pointer semantics).
        test_db.add(
            Visitor(
                site_id=site_id,
                visitor_id="v-real-merged",
                first_seen=datetime.utcnow(),
                last_seen=datetime.utcnow(),
                pages_visited=[],
                identity_status="merged",
                canonical_visitor_id=phantom.visitor_id,
            )
        )
        await test_db.commit()

        # The phantom's OWN total_pageviews is still 0 — the predicate must
        # nonetheless re-include it, which only an EXISTS pointer lookup can do.
        await test_db.refresh(phantom)
        assert phantom.total_pageviews == 0
        assert phantom.visitor_id in await _visible(), (
            "a merged phantom must count normally again"
        )
