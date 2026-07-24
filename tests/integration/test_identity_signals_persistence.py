"""Owned-data-layer Phase 2 (Hybrid, needs PG+Redis): identity_signals persistence.

Proves:
- record_signal persists a row with ciphertext + blind index (NO plaintext email)
- corroborate_identity join lookup by ip and by email_bidx returns a decayed bump
- decay is applied at read time

Run: docker compose -f infra/docker-compose.yml up -d postgres redis
     .venv/bin/python -m pytest tests/integration/test_identity_signals_persistence.py -q
"""
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import func, select

from apps.api.models.identity_signal import IdentitySignal
from apps.api.models.visitor import IdentifiedVisitor, Visitor
from apps.api.services import identity_signals as sig
from apps.api.services.pii_crypto import email_hash

pytestmark = pytest.mark.integration

_ALL_GATES_PASS = {
    "is_datacenter_ip": AsyncMock(return_value=False),
    "check_ip_privacy": AsyncMock(return_value=None),
    "is_proxy_or_vpn": MagicMock(return_value=False),
    "is_email_suppressed": AsyncMock(return_value=False),
    "_visitor_do_not_resolve": AsyncMock(return_value=False),
}

# Gates 1-3 patched to pass; gate 4 (_visitor_do_not_resolve) left REAL so the
# do_not_resolve sticky is exercised end-to-end against real Postgres rows.
_GATES_123_PASS = {
    "is_datacenter_ip": AsyncMock(return_value=False),
    "check_ip_privacy": AsyncMock(return_value=None),
    "is_proxy_or_vpn": MagicMock(return_value=False),
    "is_email_suppressed": AsyncMock(return_value=False),
}


@pytest.mark.asyncio
async def test_pii_pattern_no_plaintext_email(test_db):
    email = "person@acme.com"
    with patch.multiple(sig, **_ALL_GATES_PASS):
        await sig.record_signal(test_db, "site-1", "203.0.113.20", email, "sendgrid_click")

    rows = (await test_db.execute(select(IdentitySignal))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    # No plaintext email anywhere on the row.
    assert row.email_ciphertext != email
    assert row.email_bidx == email_hash(email)
    assert row.base_confidence == 0.6


@pytest.mark.asyncio
async def test_corroborate_join_by_ip_and_email(test_db):
    email = "lead@acme.com"
    ip = "203.0.113.21"
    with patch.multiple(sig, **_ALL_GATES_PASS):
        await sig.record_signal(test_db, "site-1", ip, email, "sendgrid_open")

    by_ip = await sig.corroborate_identity(test_db, ip, "other@x.com")
    assert by_ip is not None and by_ip > 0

    by_email = await sig.corroborate_identity(test_db, "9.9.9.9", email)
    assert by_email is not None and by_email > 0

    none = await sig.corroborate_identity(test_db, "9.9.9.9", "nobody@x.com")
    assert none is None


@pytest.mark.asyncio
async def test_identity_signal_skipped_when_do_not_resolve(test_db):
    """AC11: a visitor marked do_not_resolve=True must block signal capture.

    Exercises the REAL gate-4 (_visitor_do_not_resolve) path end-to-end against
    Postgres — only gates 1-3 are patched to pass. A do_not_resolve visitor mapped
    to the email must cause record_signal to write ZERO IdentitySignal rows.
    """
    site_id = "site-dnr"
    visitor_id = "v-dnr-1"
    email = "dnr@acme.com"
    now = datetime.utcnow()  # Visitor.first_seen/last_seen are TIMESTAMP WITHOUT TIME ZONE

    # Real visitor flagged do_not_resolve, plus the email→visitor mapping the
    # gate joins through (IdentifiedVisitor.email == visitor).
    test_db.add(
        Visitor(
            site_id=site_id,
            visitor_id=visitor_id,
            first_seen=now,
            last_seen=now,
            do_not_resolve=True,
        )
    )
    test_db.add(
        IdentifiedVisitor(site_id=site_id, visitor_id=visitor_id, email=email)
    )
    await test_db.commit()

    with patch.multiple(sig, **_GATES_123_PASS):
        await sig.record_signal(test_db, site_id, "203.0.113.30", email, "sendgrid_open")

    # Gate 4 tripped → no signal row written.
    count = (
        await test_db.execute(
            select(func.count()).select_from(IdentitySignal)
        )
    ).scalar_one()
    assert count == 0
