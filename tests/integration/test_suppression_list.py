"""Phase 02 (GDPR/CCPA) integration: the suppression list.

Against the test DB (requires local PostgreSQL via docker-compose):
- Admin-only CRUD on /api/v1/privacy/suppressions (non-admin → 403).
- Adding an entry cascades: matching identified visitors get do_not_email and
  their visitor rows get do_not_resolve.
- The resolver refuses a visitor whose captured email is on the do_not_process
  list.
- CSV export excludes do_not_sell contacts.
"""

import uuid as uuidlib
from datetime import datetime
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "P"},
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
async def admin_token(test_client, test_db) -> str:
    from apps.api.models.user import User

    email = f"admin-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()
    user.is_admin = True
    await test_db.commit()
    return token


class TestSuppressionEndpoint:
    @pytest.mark.asyncio
    async def test_non_admin_forbidden(self, test_client):
        token = await _signup(test_client, f"user-{uuidlib.uuid4().hex[:8]}@test.com")
        resp = await test_client.post(
            "/api/v1/privacy/suppressions",
            headers=_auth(token),
            json={"email": "x@y.com", "scope": "all"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_add_list_remove(self, test_client, admin_token):
        from apps.api.services.pii_crypto import email_hash

        email = f"sup-{uuidlib.uuid4().hex[:8]}@y.com"
        add = await test_client.post(
            "/api/v1/privacy/suppressions",
            headers=_auth(admin_token),
            json={"email": email, "scope": "all", "reason": "ccpa request"},
        )
        assert add.status_code == 201, add.text

        listing = await test_client.get(
            "/api/v1/privacy/suppressions", headers=_auth(admin_token)
        )
        assert listing.status_code == 200
        hashes = {e["email_hash"] for e in listing.json()}
        assert email_hash(email) in hashes  # stored as a hash, never plaintext

        remove = await test_client.delete(
            f"/api/v1/privacy/suppressions?email={email}&scope=all",
            headers=_auth(admin_token),
        )
        assert remove.status_code == 200
        assert remove.json()["count"] == 1

    @pytest.mark.asyncio
    async def test_invalid_scope_and_email(self, test_client, admin_token):
        bad_scope = await test_client.post(
            "/api/v1/privacy/suppressions",
            headers=_auth(admin_token),
            json={"email": "a@b.com", "scope": "nonsense"},
        )
        assert bad_scope.status_code == 400

        bad_email = await test_client.post(
            "/api/v1/privacy/suppressions",
            headers=_auth(admin_token),
            json={"email": "not-an-email", "scope": "all"},
        )
        assert bad_email.status_code == 400


class TestSuppressionCascade:
    @pytest.mark.asyncio
    async def test_add_cascades_to_existing(self, test_db):
        from apps.api.models.visitor import IdentifiedVisitor, Visitor
        from apps.api.services.suppression import add_suppression

        site_id = f"site_{uuidlib.uuid4().hex[:8]}"
        vid = f"v_{uuidlib.uuid4().hex[:8]}"
        email = f"cascade-{uuidlib.uuid4().hex[:8]}@y.com"
        now = datetime.utcnow()
        test_db.add(Visitor(
            site_id=site_id, visitor_id=vid, first_seen=now, last_seen=now,
            identity_status="identified", do_not_resolve=False,
        ))
        test_db.add(IdentifiedVisitor(
            site_id=site_id, visitor_id=vid, email=email, do_not_email=False,
        ))
        await test_db.commit()

        result = await add_suppression(test_db, email, scope="all")
        assert result["identified_suppressed"] >= 1
        assert result["visitors_blocked"] >= 1

        visitor = (await test_db.execute(
            select(Visitor).where(Visitor.site_id == site_id, Visitor.visitor_id == vid)
        )).scalar_one()
        identified = (await test_db.execute(
            select(IdentifiedVisitor).where(
                IdentifiedVisitor.site_id == site_id, IdentifiedVisitor.visitor_id == vid
            )
        )).scalar_one()
        await test_db.refresh(visitor)
        await test_db.refresh(identified)
        assert visitor.do_not_resolve is True
        assert identified.do_not_email is True


class TestResolverHonorsSuppression:
    @pytest.mark.asyncio
    async def test_captured_email_on_list_blocks_resolution(self, test_db):
        from apps.api.models.visitor import Visitor
        from apps.api.models.visitor_email import VisitorEmail
        from apps.api.services.identity_resolver import IdentityResolver
        from apps.api.services.suppression import add_suppression

        site_id = f"site_{uuidlib.uuid4().hex[:8]}"
        vid = f"v_{uuidlib.uuid4().hex[:8]}"
        email = f"block-{uuidlib.uuid4().hex[:8]}@y.com"
        now = datetime.utcnow()

        await add_suppression(test_db, email, scope="do_not_process")
        test_db.add(Visitor(
            site_id=site_id, visitor_id=vid, first_seen=now, last_seen=now,
            intent_score=80.0, identity_status="anonymous",
            ip_address="203.0.113.10", do_not_resolve=False,
        ))
        test_db.add(VisitorEmail(site_id=site_id, visitor_id=vid, email=email, source="form"))
        await test_db.commit()

        visitor = (await test_db.execute(
            select(Visitor).where(Visitor.site_id == site_id, Visitor.visitor_id == vid)
        )).scalar_one()

        resolver = IdentityResolver(db=test_db, redis_client=MagicMock())
        result = await resolver.resolve(visitor)
        assert result is None


class TestExportExcludesSuppressed:
    @pytest.mark.asyncio
    async def test_do_not_sell_excluded_from_export(self, test_db):
        from apps.api.models.segment import Segment, SegmentMember
        from apps.api.models.visitor import IdentifiedVisitor
        from apps.api.services.csv_exporter import _get_segment_visitors
        from apps.api.services.suppression import add_suppression

        site_id = f"site_{uuidlib.uuid4().hex[:8]}"
        keep_email = f"keep-{uuidlib.uuid4().hex[:8]}@y.com"
        drop_email = f"drop-{uuidlib.uuid4().hex[:8]}@y.com"

        seg = Segment(site_id=site_id, name="Seg")
        test_db.add(seg)
        await test_db.flush()

        for vid, email in ((f"v_keep_{uuidlib.uuid4().hex[:6]}", keep_email),
                           (f"v_drop_{uuidlib.uuid4().hex[:6]}", drop_email)):
            test_db.add(IdentifiedVisitor(
                site_id=site_id, visitor_id=vid, email=email, do_not_email=False,
                resolution_provider="form_capture",
            ))
            test_db.add(SegmentMember(segment_id=seg.id, site_id=site_id, visitor_id=vid))
        await test_db.commit()

        await add_suppression(test_db, drop_email, scope="do_not_sell")

        rows = await _get_segment_visitors(test_db, str(seg.id))
        emails = {r["email"] for r in rows}
        assert keep_email in emails
        assert drop_email not in emails
