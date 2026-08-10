"""Integration tests — privacy-hold Clear endpoint (Option D).

POST /visitors/{site_id}/{visitor_id}/clear-privacy-hold flips a single held
visitor's sticky ``do_not_resolve`` back to False, audited via structlog, with NO
migration, NO Identify bypass, and NO suppression edit. These tests pin the
endpoint's wiring (scoped flip, cross-tenant 404, idempotency, no-bypass,
does-not-unsuppress, re-optout re-stick, audit event) against the real test DB.

Requires: PostgreSQL running locally (docker-compose, localhost:5433).

Scenario → SPEC AC map (see privacy-hold-clear_PLAN_09-08-26.md §Verification Evidence):
- test_integration_clear_hold_scoped_flip        → AC-4  (V-int-scoped-flip)
- test_integration_clear_hold_cross_tenant_404   → AC-5  (V-int-cross-tenant-404)
- test_integration_clear_unknown_visitor_404     → AC-5  (unknown id, no write)
- test_integration_no_hold_bypass                → AC-7  (V-int-no-bypass)
- test_integration_clear_does_not_unsuppress     → AC-10 (V-int-does-not-unsuppress)
- test_integration_clear_idempotent_noop         → AC-11 (V-int-idempotent)
- test_integration_clear_then_reoptout_resticks  → AC-8  (V-int-reoptout-resticks)
- test_clear_hold_audit_record                   → AC-9  (V-int-audit)
"""

import uuid as uuidlib
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "Hold Tester"},
    )
    if resp.status_code != 200:
        resp = await test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "testpass123"}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _visitor(site_id: str, visitor_id: str, **overrides):
    from apps.api.models.visitor import Visitor

    defaults = dict(
        site_id=site_id,
        visitor_id=visitor_id,
        first_seen=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        pages_visited=[],
        ip_address="203.0.113.7",
        intent_score=75.0,
        identity_status="anonymous",
        enrichment_status="pending",
    )
    defaults.update(overrides)
    return Visitor(**defaults)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class _FakeResolver:
    """Stand-in for IdentityResolver: marks the visitor identified + persists an
    IdentifiedVisitor, mirroring what the real resolver does on a hit. Mirrors
    the real resolve() signature (the endpoint passes force_retry through)."""

    def __init__(self, db, redis_client=None):
        self.db = db

    async def resolve(self, visitor, source_agent_visit_id=None, force_retry=False):
        from apps.api.models.visitor import IdentifiedVisitor

        visitor.identity_status = "identified"
        iv = IdentifiedVisitor(
            site_id=visitor.site_id,
            visitor_id=visitor.visitor_id,
            email="found@acme.com",
            full_name="Found Person",
            resolution_provider="leadpipe",
            confidence_score=0.9,
        )
        self.db.add(iv)
        await self.db.commit()
        return iv


class _FakeEnricher:
    def __init__(self, db):
        self.db = db

    async def enrich_tier1(self, visitor, identified):
        return None


def _patch_resolver(monkeypatch, resolver=_FakeResolver):
    monkeypatch.setattr("apps.api.routers.visitors.IdentityResolver", resolver)
    monkeypatch.setattr("apps.api.routers.visitors.Enricher", _FakeEnricher)


async def _mk_user_site(test_client, test_db, label: str):
    """Sign up a user + create one Site they own. Returns (token, user, site_id)."""
    from apps.api.models.site import Site
    from apps.api.models.user import User

    email = f"{label}-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (
        await test_db.execute(select(User).where(User.email == email))
    ).scalar_one()

    site_id = f"{label}_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(
        Site(site_id=site_id, user_id=user.id, name="Hold Site", url="https://h.example.com")
    )
    await test_db.commit()
    return token, user, site_id


@pytest_asyncio.fixture
async def hold_setup(test_client, test_db):
    """One user/site with two HELD visitors + one not-held visitor."""
    token, user, site_id = await _mk_user_site(test_client, test_db, "hold")
    test_db.add(_visitor(site_id, "v-held", do_not_resolve=True))
    test_db.add(_visitor(site_id, "v-held-2", do_not_resolve=True))
    test_db.add(_visitor(site_id, "v-clear", do_not_resolve=False))
    await test_db.commit()
    return {"token": token, "site_id": site_id, "user": user}


async def _do_not_resolve(test_db, site_id: str, visitor_id: str) -> bool:
    from apps.api.models.visitor import Visitor

    return (
        await test_db.execute(
            select(Visitor.do_not_resolve).where(
                Visitor.site_id == site_id, Visitor.visitor_id == visitor_id
            )
        )
    ).scalar_one()


class TestClearPrivacyHold:
    @pytest.mark.asyncio
    async def test_integration_clear_hold_scoped_flip(self, test_client, test_db, hold_setup):
        """AC-4: clear flips exactly ONE (site,visitor); a second held row is untouched."""
        site_id = hold_setup["site_id"]
        resp = await test_client.post(
            f"/api/v1/visitors/{site_id}/v-held/clear-privacy-hold",
            headers=_auth(hold_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data == {"visitor_id": "v-held", "do_not_resolve": False, "cleared": True}

        assert await _do_not_resolve(test_db, site_id, "v-held") is False
        # The OTHER held visitor is untouched.
        assert await _do_not_resolve(test_db, site_id, "v-held-2") is True

    @pytest.mark.asyncio
    async def test_integration_clear_hold_cross_tenant_404(self, test_client, test_db, hold_setup):
        """AC-5: a different user/site calling clear on the first site's visitor →
        404, and the first visitor stays held (no write)."""
        # Second tenant.
        other_token, _other_user, _other_site = await _mk_user_site(
            test_client, test_db, "other"
        )
        resp = await test_client.post(
            f"/api/v1/visitors/{hold_setup['site_id']}/v-held/clear-privacy-hold",
            headers=_auth(other_token),
        )
        assert resp.status_code == 404
        # No write happened — still held.
        assert await _do_not_resolve(test_db, hold_setup["site_id"], "v-held") is True

    @pytest.mark.asyncio
    async def test_integration_clear_unknown_visitor_404(self, test_client, hold_setup):
        """AC-5 (miss): unknown visitor id → 404."""
        resp = await test_client.post(
            f"/api/v1/visitors/{hold_setup['site_id']}/does-not-exist/clear-privacy-hold",
            headers=_auth(hold_setup["token"]),
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_integration_no_hold_bypass(self, test_client, hold_setup, monkeypatch):
        """AC-7: still-held row → /resolve short-circuits privacy_opt_out; after
        clear → /resolve reaches the waterfall (fake resolver identifies)."""
        _patch_resolver(monkeypatch)
        site_id = hold_setup["site_id"]

        # Held row: resolve refuses via the unchanged do_not_resolve short-circuit.
        held = await test_client.post(
            f"/api/v1/visitors/{site_id}/v-held/resolve",
            headers=_auth(hold_setup["token"]),
        )
        assert held.status_code == 200, held.text
        held_data = held.json()
        assert held_data["status"] == "anonymous"
        assert held_data["skip_reason"] == "privacy_opt_out"

        # Clear the hold, then resolve reaches the waterfall.
        cleared = await test_client.post(
            f"/api/v1/visitors/{site_id}/v-held/clear-privacy-hold",
            headers=_auth(hold_setup["token"]),
        )
        assert cleared.status_code == 200, cleared.text

        after = await test_client.post(
            f"/api/v1/visitors/{site_id}/v-held/resolve",
            headers=_auth(hold_setup["token"]),
        )
        assert after.status_code == 200, after.text
        assert after.json()["status"] == "identified"

    @pytest.mark.asyncio
    async def test_integration_clear_does_not_unsuppress(self, test_client, test_db):
        """AC-10: a visitor whose email is on the do_not_process suppression list
        stays unresolvable after clear — clearing the hold is NOT un-suppressing.
        Uses the REAL resolver so the suppression gate actually runs."""
        from apps.api.models.visitor_email import VisitorEmail
        from apps.api.services.suppression import add_suppression, is_email_suppressed

        token, _user, site_id = await _mk_user_site(test_client, test_db, "supp")
        test_db.add(_visitor(site_id, "v-supp"))
        test_db.add(
            VisitorEmail(site_id=site_id, visitor_id="v-supp", email="suppressed@x.com", source="form")
        )
        await test_db.commit()

        # Suppress the email (do_not_process) — cascades do_not_resolve=True.
        await add_suppression(test_db, "suppressed@x.com", scope="do_not_process")
        assert await _do_not_resolve(test_db, site_id, "v-supp") is True

        # Clear the privacy hold.
        cleared = await test_client.post(
            f"/api/v1/visitors/{site_id}/v-supp/clear-privacy-hold",
            headers=_auth(token),
        )
        assert cleared.status_code == 200, cleared.text
        assert await _do_not_resolve(test_db, site_id, "v-supp") is False

        # Resolve (REAL resolver) must still refuse — suppression gate intact.
        resolved = await test_client.post(
            f"/api/v1/visitors/{site_id}/v-supp/resolve",
            headers=_auth(token),
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["status"] != "identified"

        # The suppression entry itself is untouched.
        assert await is_email_suppressed(test_db, "suppressed@x.com", "do_not_process") is True

    @pytest.mark.asyncio
    async def test_integration_clear_idempotent_noop(self, test_client, test_db, hold_setup):
        """AC-11: clearing a not-held visitor → 200, cleared:false, no error."""
        site_id = hold_setup["site_id"]
        resp = await test_client.post(
            f"/api/v1/visitors/{site_id}/v-clear/clear-privacy-hold",
            headers=_auth(hold_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "visitor_id": "v-clear",
            "do_not_resolve": False,
            "cleared": False,
        }
        assert await _do_not_resolve(test_db, site_id, "v-clear") is False

    @pytest.mark.asyncio
    async def test_integration_clear_then_reoptout_resticks(self, test_client, test_db, hold_setup):
        """AC-8: clear → a later opt-out event re-aggregates → do_not_resolve
        re-sticks to True (aggregator BOOL_OR + sticky OR unchanged)."""
        from apps.api.models.event import Event
        from apps.api.services.visitor_aggregator import aggregate_visitors_for_site

        site_id = hold_setup["site_id"]
        # Clear the hold first.
        cleared = await test_client.post(
            f"/api/v1/visitors/{site_id}/v-held/clear-privacy-hold",
            headers=_auth(hold_setup["token"]),
        )
        assert cleared.status_code == 200, cleared.text
        assert await _do_not_resolve(test_db, site_id, "v-held") is False

        # A later opt-out event arrives; re-aggregation must re-stick the flag.
        now = datetime.utcnow()
        test_db.add(
            Event(
                event_id=uuidlib.uuid4().hex,
                site_id=site_id,
                visitor_id="v-held",
                event_type="pageview",
                url="https://example.com/pricing",
                created_at=now,
                optout=True,
            )
        )
        await test_db.commit()
        await aggregate_visitors_for_site(test_db, site_id)

        assert await _do_not_resolve(test_db, site_id, "v-held") is True

    @pytest.mark.asyncio
    async def test_clear_hold_audit_record(self, test_client, hold_setup):
        """AC-9: a successful clear emits a `privacy_hold_cleared` structlog event
        with actor/site/truncated-visitor/was_held — and NO PII (no email/raw)."""
        from structlog.testing import capture_logs

        site_id = hold_setup["site_id"]
        with capture_logs() as logs:
            resp = await test_client.post(
                f"/api/v1/visitors/{site_id}/v-held/clear-privacy-hold",
                headers=_auth(hold_setup["token"]),
            )
        assert resp.status_code == 200, resp.text

        events = [e for e in logs if e.get("event") == "privacy_hold_cleared"]
        assert len(events) == 1, events
        ev = events[0]
        assert ev["site_id"] == site_id
        assert ev["visitor_id"] == "v-held"[:8]
        assert ev["user_id"] == str(hold_setup["user"].id)
        assert ev["was_held"] is True
        # No PII: no email address anywhere in the event payload.
        blob = " ".join(str(v) for v in ev.values())
        assert "@" not in blob
