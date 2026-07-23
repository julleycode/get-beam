"""Owned-data-layer Phase 1 (Hybrid, needs PG+Redis): durable persistence.

Proves company_graph survives a real resolver call boundary:
- write-through inserts a row
- a second resolve for the same (ip, source) UPDATEs (upsert on conflict), not
  a duplicate
- read-time staleness flag reflects last_verified vs the configured window

Run: docker compose -f infra/docker-compose.yml up -d postgres redis
     .venv/bin/python -m pytest tests/integration/test_company_graph_persistence.py -q
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from apps.api.models.company_graph import CompanyGraphNode
from apps.api.services import company_resolver as cr

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_real_pg_insert_and_conflict_update(test_db):
    ip = "203.0.113.55"

    await cr._write_through_company_graph(test_db, ip, "acme.com", "Acme", "rdns", 0.5)
    rows = (
        await test_db.execute(
            select(CompanyGraphNode).where(CompanyGraphNode.ip == ip)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].domain == "acme.com"

    # Same (ip, source) → UPDATE, not a second row.
    await cr._write_through_company_graph(test_db, ip, "acme-corp.com", "Acme Corp", "rdns", 0.8)
    rows = (
        await test_db.execute(
            select(CompanyGraphNode).where(CompanyGraphNode.ip == ip)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].domain == "acme-corp.com"
    assert rows[0].confidence == 0.8

    # A different source for the same IP is a distinct row.
    await cr._write_through_company_graph(test_db, ip, "acme.com", None, "paid_ip", 0.7)
    rows = (
        await test_db.execute(
            select(CompanyGraphNode).where(CompanyGraphNode.ip == ip)
        )
    ).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_read_staleness_flag_across_boundary(test_db):
    ip = "203.0.113.77"
    await cr._write_through_company_graph(test_db, ip, "fresh.com", None, "rdns", 0.5)

    read = await cr._read_company_graph(test_db, ip)
    assert read is not None
    assert read.node.domain == "fresh.com"
    # Freshly written → within any reasonable window → not stale.
    assert read.needs_revalidation is False

    # Force the row old and confirm the read flags re-validation.
    read.node.last_verified = datetime.now(timezone.utc) - timedelta(days=400)
    await test_db.commit()
    read2 = await cr._read_company_graph(test_db, ip)
    assert read2.needs_revalidation is True
