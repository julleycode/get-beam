"""Integration test — EvalLayer Phase 4 verification sweep end-to-end.

Docker known-gap: requires a real (test) Postgres. Proves the sweep query and
``upgrade_verification_method`` UPDATE execute correctly against the real
schema — the property unit tests (mocked AsyncSession) cannot prove.

Runs under ``MOCK_EXTERNAL_APIS=true`` so the mock CIDR (10.99.0.0/24 for
openai) deterministically matches without any live network call.
"""

import uuid as uuidlib
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from apps.api.config import settings
from apps.api.models.agent_visit import AgentVisit
from apps.api.services.agent_verification import run_verification_sweep

pytestmark = pytest.mark.integration


def _agent(site_id: str, vendor: str, token: str, ip: str) -> AgentVisit:
    now = datetime.now(timezone.utc)
    return AgentVisit(
        site_id=site_id,
        vendor=vendor,
        product_or_ua_token=token,
        verification_method="ua-only",
        first_seen_at=now,
        last_seen_at=now,
        ip_address=ip,
        page_paths=["/"],
        visit_count=1,
    )


@pytest.mark.asyncio
async def test_sweep_upgrades_only_matching_openai_row(test_db, monkeypatch):
    monkeypatch.setattr(settings, "mock_external_apis", True)
    site_id = f"sweep_site_{uuidlib.uuid4().hex[:8]}"

    # Matching openai row (IP in mock 10.99.0.0/24) → should upgrade.
    match = _agent(site_id, "openai", "GPTBot", "10.99.0.5")
    # Non-matching openai row (IP outside mock block) → stays ua-only.
    no_match = _agent(site_id, "openai", "OAI-SearchBot", "8.8.8.8")
    # Anthropic row (structural ceiling) → stays ua-only even with a matching IP.
    anthro = _agent(site_id, "anthropic", "ClaudeBot", "10.99.0.5")
    for row in (match, no_match, anthro):
        test_db.add(row)
    await test_db.commit()

    await run_verification_sweep(test_db)

    async def _method(row_id) -> str:
        r = await test_db.execute(
            select(AgentVisit.verification_method).where(AgentVisit.id == row_id)
        )
        return r.scalar_one()

    assert await _method(match.id) == "ip-verified"
    assert await _method(no_match.id) == "ua-only"
    assert await _method(anthro.id) == "ua-only"
