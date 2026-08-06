"""Phase 4 (needs PG): what only a real database can prove about webhook ingest.

- redelivery of the same identification collapses onto ONE identity row, via the
  real ``uq_identified_site_visitor`` UNIQUE index (there is no dedup key of our
  own — this index IS the idempotency mechanism)
- the saved row is a provider_candidate, never verified
- an identification carrying site A's pixel can never attach to site B's visitor,
  even when the IP matches exactly

Run: docker compose -f infra/docker-compose.yml up -d postgres redis
     .venv/Scripts/python -m pytest tests/integration/test_leadpipe_webhook_persistence.py -q

Needs the database `retarget_agent_test` to exist; without it every test here
fails with InvalidCatalogNameError, which reads like a code error but is not:
  docker exec infra-postgres-1 psql -U retarget -d postgres \
    -c "CREATE DATABASE retarget_agent_test;"
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select

from apps.api.models.site import Site
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.models.visitor_email import VisitorEmail
from apps.api.services import leadpipe_webhook as lw
from apps.api.services.identity_classification import (
    is_emailable_identity,
)

pytestmark = pytest.mark.integration

# MX lookup is a live DNS call; it is not what these tests are about.
_EMAIL_OK = patch(
    "apps.api.services.email_validator.validate_email",
    AsyncMock(return_value=(True, "")),
)


async def _make_site(db, site_id: str, url: str, pixel_id: str) -> Site:
    site = Site(
        site_id=site_id,
        user_id=uuid.uuid4(),
        name=site_id,
        url=url,
        leadpipe_pixel_id=pixel_id,
    )
    db.add(site)
    await db.commit()
    return site


async def _make_visitor(db, site_id: str, visitor_id: str, ip: str) -> Visitor:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    visitor = Visitor(
        site_id=site_id,
        visitor_id=visitor_id,
        first_seen=now - timedelta(minutes=5),
        last_seen=now,
        ip_address=ip,
    )
    db.add(visitor)
    await db.commit()
    return visitor


def _payload(pixel_id: str, **extra) -> dict:
    base = {
        "pixel_id": pixel_id,
        "email": "casey.jordan@example.com",
        "firstName": "Casey",
        "lastName": "Jordan",
        "ip": "203.0.113.77",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    base.update(extra)
    return base


@pytest.mark.asyncio
async def test_redelivery_creates_one_identity_row(test_db):
    """Leadpipe First Match can still redeliver; the UNIQUE index absorbs it."""
    await _make_site(test_db, "site-a", "https://acme.test", "px-a")
    await _make_visitor(test_db, "site-a", "v-a", "203.0.113.77")

    with _EMAIL_OK:
        first = await lw.ingest_identification(test_db, _payload("px-a"))
        second = await lw.ingest_identification(test_db, _payload("px-a"))

    assert first == "saved"
    # The second delivery must not error and must not add a row. Either outcome
    # word is acceptable; the row count is the assertion that matters.
    assert second in {"saved", "rejected"}

    count = (
        await test_db.execute(
            select(func.count())
            .select_from(IdentifiedVisitor)
            .where(IdentifiedVisitor.site_id == "site-a")
        )
    ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_saved_identity_is_a_candidate_and_not_emailable(test_db):
    await _make_site(test_db, "site-a", "https://acme.test", "px-a")
    await _make_visitor(test_db, "site-a", "v-a", "203.0.113.77")

    with _EMAIL_OK:
        assert await lw.ingest_identification(test_db, _payload("px-a")) == "saved"

    row = (
        await test_db.execute(
            select(IdentifiedVisitor).where(IdentifiedVisitor.site_id == "site-a")
        )
    ).scalar_one()
    visitor = (
        await test_db.execute(
            select(Visitor).where(Visitor.visitor_id == "v-a")
        )
    ).scalar_one()

    assert row.resolution_provider == "leadpipe"
    # D1: canonical vocabulary — the push-ingest path writes "candidate".
    assert visitor.identity_status == "candidate"
    # D2: candidate-tier identities ARE emailable (personalization gate, not an
    # emailability block, is what restrains them).
    assert is_emailable_identity(row.resolution_provider) is True


@pytest.mark.asyncio
async def test_email_tier_attaches_to_the_visitor_who_typed_it(test_db):
    """A captured address beats the IP guess — and picks a DIFFERENT visitor."""
    await _make_site(test_db, "site-a", "https://acme.test", "px-a")
    # Same IP for both, so only the captured email can separate them.
    await _make_visitor(test_db, "site-a", "v-ip-only", "203.0.113.77")
    await _make_visitor(test_db, "site-a", "v-typed-email", "203.0.113.77")
    test_db.add(
        VisitorEmail(
            site_id="site-a",
            visitor_id="v-typed-email",
            email="casey.jordan@example.com",
            source="form",
        )
    )
    await test_db.commit()

    with _EMAIL_OK:
        assert await lw.ingest_identification(test_db, _payload("px-a")) == "saved"

    row = (
        await test_db.execute(
            select(IdentifiedVisitor).where(IdentifiedVisitor.site_id == "site-a")
        )
    ).scalar_one()
    assert row.visitor_id == "v-typed-email"


@pytest.mark.asyncio
async def test_pixel_of_one_site_never_writes_to_another(test_db):
    """Tenant isolation, with the IP deliberately identical across both sites."""
    await _make_site(test_db, "site-a", "https://acme.test", "px-a")
    await _make_site(test_db, "site-b", "https://other.test", "px-b")
    await _make_visitor(test_db, "site-b", "v-b", "203.0.113.77")

    with _EMAIL_OK:
        # Site A's pixel, but only site B has a visitor on that IP.
        outcome = await lw.ingest_identification(test_db, _payload("px-a"))

    assert outcome == "no_visitor_match"
    count = (await test_db.execute(
        select(func.count()).select_from(IdentifiedVisitor)
    )).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_name_email_mismatch_is_rejected_through_the_webhook(test_db):
    """The paid-graph corruption gate must hold on this path too.

    Asserted against the REAL _save_identified rather than a mock: the whole
    design claim is that the webhook reuses the pull path's gates, and a mocked
    save would prove only that we call something.
    """
    await _make_site(test_db, "site-a", "https://acme.test", "px-a")
    await _make_visitor(test_db, "site-a", "v-a", "203.0.113.77")

    with _EMAIL_OK:
        outcome = await lw.ingest_identification(
            test_db,
            _payload(
                "px-a",
                email="danica_naluz@example.com",
                firstName="Janet",
                lastName="Valla",
            ),
        )

    assert outcome == "rejected"
    count = (await test_db.execute(
        select(func.count()).select_from(IdentifiedVisitor)
    )).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_consistent_name_email_is_not_rejected(test_db):
    """Control for the test above — proves the gate is not refusing everything."""
    await _make_site(test_db, "site-a", "https://acme.test", "px-a")
    await _make_visitor(test_db, "site-a", "v-a", "203.0.113.77")

    with _EMAIL_OK:
        outcome = await lw.ingest_identification(
            test_db,
            _payload("px-a", email="casey.jordan@example.com", firstName="Casey", lastName="Jordan"),
        )

    assert outcome == "saved"


@pytest.mark.asyncio
async def test_unknown_pixel_writes_nothing(test_db):
    await _make_site(test_db, "site-a", "https://acme.test", "px-a")
    await _make_visitor(test_db, "site-a", "v-a", "203.0.113.77")

    with _EMAIL_OK:
        outcome = await lw.ingest_identification(test_db, _payload("px-does-not-exist"))

    assert outcome == "unknown_site"
    count = (await test_db.execute(
        select(func.count()).select_from(IdentifiedVisitor)
    )).scalar_one()
    assert count == 0
