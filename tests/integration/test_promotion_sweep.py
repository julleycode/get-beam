"""Integration tests for identity-honesty Phase 5 — click→verified promotion sweep.

Covers SPEC AC11: a tokenized-link click is recognized as a verified identity
within <=5 minutes via a batch sweep that runs AFTER the /ingest request
completes — never synchronously inside it.

Two distinct promotion outcomes are asserted, because they are NOT the same
identity_status:
  * plain utm click (no pre-existing contact for that email) -> "identified"
  * imported-contact click (phantom import row already holds that email) ->
    "merged" + canonical_visitor_id pointing at the phantom (pointer semantics,
    per identity_resolver.py's email-dedup branch)

Requires: PostgreSQL running locally (via docker-compose).
"""

import json
import uuid as uuidlib
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration

SLA = timedelta(minutes=5)


@pytest.fixture(autouse=True)
def _no_dns_email_validation(monkeypatch):
    """Skip the MX-record DNS lookup inside validate_email.

    The sweep's promotion path runs every email through validate_email; a live
    DNS resolve would make these tests non-deterministic and network-dependent.
    """
    async def _always_valid(email: str):
        return (True, "")

    monkeypatch.setattr(
        "apps.api.services.email_validator.validate_email", _always_valid
    )


async def _make_site(test_client, test_db, prefix: str) -> str:
    from apps.api.models.site import Site
    from apps.api.models.user import User

    email = f"{prefix}-{uuidlib.uuid4().hex[:8]}@test.com"
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "Sweep Tester"},
    )
    assert resp.status_code == 200, resp.text
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()
    site_id = f"{prefix}_{uuidlib.uuid4().hex[:8]}"
    test_db.add(
        Site(
            site_id=site_id,
            user_id=user.id,
            name="Sweep Site",
            url="https://sweep.example.com",
        )
    )
    await test_db.commit()
    return site_id


async def _seed_click(test_db, site_id: str, visitor_id: str, email: str) -> datetime:
    """Simulate what /ingest writes for a tokenized-link click: an anonymous
    Visitor plus a fresh source='utm' visitor_emails row. Returns click time."""
    from apps.api.models.visitor import Visitor
    from apps.api.models.visitor_email import VisitorEmail

    clicked_at = datetime.now(timezone.utc)
    test_db.add(
        Visitor(
            visitor_id=visitor_id,
            site_id=site_id,
            identity_status="anonymous",
        )
    )
    test_db.add(
        VisitorEmail(
            site_id=site_id,
            visitor_id=visitor_id,
            email=email,
            source="utm",
        )
    )
    await test_db.commit()
    return clicked_at


async def _seed_phantom_contact(test_db, site_id: str, email: str) -> str:
    """Seed a Phase 4 phantom import contact (Visitor + identified row)."""
    from apps.api.models.visitor import IdentifiedVisitor, Visitor

    contact_id = uuidlib.uuid4()
    visitor_id = f"import:{contact_id}"
    test_db.add(
        Visitor(
            visitor_id=visitor_id,
            site_id=site_id,
            identity_status="identified",
            is_imported_contact=True,
        )
    )
    test_db.add(
        IdentifiedVisitor(
            visitor_id=visitor_id,
            site_id=site_id,
            email=email,
            full_name="Ada Lovelace",
            resolution_provider="csv_import",
        )
    )
    await test_db.commit()
    return visitor_id


@pytest_asyncio.fixture
async def sweep_site(test_client, test_db):
    return await _make_site(test_client, test_db, "sweep")


class TestPromotionSweepSLA:
    @pytest.mark.asyncio
    async def test_plain_click_promotes_within_sla(self, test_db, sweep_site):
        """AC11-a: a plain utm click promotes the visitor to 'identified'."""
        from apps.api.models.visitor import Visitor
        from apps.api.services.promotion_sweep_runner import run_promotion_sweep_once

        visitor_id = f"vis-{uuidlib.uuid4().hex[:10]}"
        email = f"plain-{uuidlib.uuid4().hex[:8]}@example.com"
        clicked_at = await _seed_click(test_db, sweep_site, visitor_id, email)

        counters = await run_promotion_sweep_once(test_db)
        promoted_at = datetime.now(timezone.utc)

        assert counters["processed"] >= 1
        assert counters["promoted"] >= 1
        assert counters["unexpected_paid"] == 0, (
            "a swept row must never reach the paid provider waterfall"
        )

        visitor = (
            await test_db.execute(
                select(Visitor).where(Visitor.visitor_id == visitor_id)
            )
        ).scalar_one()
        await test_db.refresh(visitor)
        assert visitor.identity_status == "identified"
        assert promoted_at - clicked_at <= SLA

    @pytest.mark.asyncio
    async def test_imported_contact_click_promotes_within_sla(self, test_db, sweep_site):
        """AC11-b: an imported contact's click merges onto the phantom contact.

        POINTER semantics — the click-derived visitor becomes 'merged' with
        canonical_visitor_id set; the phantom's own identity row is untouched.
        """
        from apps.api.models.visitor import IdentifiedVisitor, Visitor
        from apps.api.services.promotion_sweep_runner import run_promotion_sweep_once

        email = f"ada-{uuidlib.uuid4().hex[:8]}@example.com"
        phantom_id = await _seed_phantom_contact(test_db, sweep_site, email)

        visitor_id = f"vis-{uuidlib.uuid4().hex[:10]}"
        clicked_at = await _seed_click(test_db, sweep_site, visitor_id, email)

        counters = await run_promotion_sweep_once(test_db)
        promoted_at = datetime.now(timezone.utc)

        assert counters["merged"] >= 1
        assert counters["unexpected_paid"] == 0

        visitor = (
            await test_db.execute(
                select(Visitor).where(Visitor.visitor_id == visitor_id)
            )
        ).scalar_one()
        await test_db.refresh(visitor)
        assert visitor.identity_status == "merged"
        assert visitor.canonical_visitor_id == phantom_id

        phantom = (
            await test_db.execute(
                select(Visitor).where(Visitor.visitor_id == phantom_id)
            )
        ).scalar_one()
        assert phantom.identity_status == "identified"

        phantom_identity = (
            await test_db.execute(
                select(IdentifiedVisitor).where(
                    IdentifiedVisitor.visitor_id == phantom_id
                )
            )
        ).scalar_one()
        assert phantom_identity.email == email

        # No duplicate identity row was created for the click-derived visitor.
        dupes = (
            await test_db.execute(
                select(IdentifiedVisitor).where(
                    IdentifiedVisitor.visitor_id == visitor_id
                )
            )
        ).scalars().all()
        assert dupes == []
        assert promoted_at - clicked_at <= SLA


class TestIngestStaysNonBlocking:
    @pytest.mark.asyncio
    async def test_ingest_does_not_block_on_resolution(
        self, test_client, test_db, sweep_site
    ):
        """AC11-c: /ingest writes the email signal and returns — it never runs
        identity resolution inline. Promotion only happens once the sweep runs."""
        from apps.api.models.visitor import IdentifiedVisitor, Visitor
        from apps.api.models.visitor_email import VisitorEmail
        from apps.api.services.link_decorator import generate_bid
        from apps.api.services.promotion_sweep_runner import run_promotion_sweep_once

        visitor_id = f"vis-{uuidlib.uuid4().hex[:10]}"
        email = f"click-{uuidlib.uuid4().hex[:8]}@example.com"
        bid = generate_bid(email)
        assert bid, "tokenized-link _bid generation requires an encryption key"

        payload = {
            "site_id": sweep_site,
            "visitor_id": visitor_id,
            "events": [
                {
                    "type": "utm_identify",
                    "url": f"https://sweep.example.com/?_bid={bid}",
                    "page_path": "/",
                    "bid": bid,
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
            ],
        }
        resp = await test_client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 204

        captured = (
            await test_db.execute(
                select(VisitorEmail).where(
                    VisitorEmail.site_id == sweep_site,
                    VisitorEmail.visitor_id == visitor_id,
                )
            )
        ).scalars().all()
        assert len(captured) == 1
        assert captured[0].source == "utm"

        # Resolution is deferred: nothing identified the visitor during /ingest.
        assert (
            await test_db.execute(
                select(IdentifiedVisitor).where(
                    IdentifiedVisitor.visitor_id == visitor_id
                )
            )
        ).scalar_one_or_none() is None
        visitor = (
            await test_db.execute(
                select(Visitor).where(Visitor.visitor_id == visitor_id)
            )
        ).scalar_one()
        assert visitor.identity_status not in ("identified", "merged")

        # ...and the sweep is what promotes them.
        await run_promotion_sweep_once(test_db)
        await test_db.refresh(visitor)
        assert visitor.identity_status in ("identified", "merged")


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_sweep_idempotent(self, test_db, sweep_site):
        """safety-1: a second sweep over an already-promoted row is a no-op."""
        from apps.api.models.visitor import IdentifiedVisitor, Visitor
        from apps.api.services.promotion_sweep_runner import run_promotion_sweep_once

        visitor_id = f"vis-{uuidlib.uuid4().hex[:10]}"
        email = f"idem-{uuidlib.uuid4().hex[:8]}@example.com"
        await _seed_click(test_db, sweep_site, visitor_id, email)

        await run_promotion_sweep_once(test_db)
        second = await run_promotion_sweep_once(test_db)

        visitor = (
            await test_db.execute(
                select(Visitor).where(Visitor.visitor_id == visitor_id)
            )
        ).scalar_one()
        await test_db.refresh(visitor)
        assert visitor.identity_status == "identified"

        rows = (
            await test_db.execute(
                select(IdentifiedVisitor).where(
                    IdentifiedVisitor.visitor_id == visitor_id
                )
            )
        ).scalars().all()
        assert len(rows) == 1

        # Terminal-success rows are excluded from the query, so the second pass
        # does not even re-process them.
        assert second["promoted"] == 0
        assert second["merged"] == 0
        assert second["unexpected_paid"] == 0
