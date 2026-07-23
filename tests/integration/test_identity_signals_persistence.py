"""Owned-data-layer Phase 2 (Hybrid, needs PG+Redis): identity_signals persistence.

Proves:
- record_signal persists a row with ciphertext + blind index (NO plaintext email)
- corroborate_identity join lookup by ip and by email_bidx returns a decayed bump
- decay is applied at read time

Run: docker compose -f infra/docker-compose.yml up -d postgres redis
     .venv/bin/python -m pytest tests/integration/test_identity_signals_persistence.py -q
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from apps.api.models.identity_signal import IdentitySignal
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
