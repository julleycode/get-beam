"""Integration tests for Phase 6: public-surface PII / auth fixes.

Requires PostgreSQL running locally (via docker-compose); runs in CI.

Covers:
- POST /demo/identify (unauthenticated) must NOT return a person's PII just
  because the caller supplied a fingerprint that exists on ANOTHER tenant's
  site (the cross-tenant BeamIdentityNode reuse was removed).
- Legacy POST /auth/signup hard-404s in production (invite-gate bypass closed).
"""

import pytest
import pytest_asyncio

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def seeded_other_tenant_node(test_engine):
    """A BeamIdentityNode that exists only on a DIFFERENT tenant's site."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from apps.api.models.beam_identity import BeamIdentityNode

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        s.add(
            BeamIdentityNode(
                fingerprint="fp2_tenant_a_secret",
                email="victim@othercorp.com",
                full_name="Victim Person",
                confidence_score=0.99,
                source_site_id="site-of-tenant-A",
                source_provider="leadpipe",
            )
        )
        await s.commit()
    return "fp2_tenant_a_secret"


class TestDemoNoCrossTenantLeak:
    @pytest.mark.asyncio
    async def test_demo_identify_does_not_leak_other_tenant_pii(
        self, test_client, seeded_other_tenant_node
    ):
        resp = await test_client.post(
            "/api/v1/demo/identify",
            json={"fingerprint": seeded_other_tenant_node},
            headers={"User-Agent": "pytest"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("email") != "victim@othercorp.com"
        assert data.get("full_name") != "Victim Person"
        assert data.get("resolution_provider") != "beam_identity_graph"


class TestLegacySignupGatedInProd:
    @pytest.mark.asyncio
    async def test_signup_404_in_production(self, test_client, monkeypatch):
        from apps.api.config import settings

        monkeypatch.setattr(settings, "app_env", "production")
        resp = await test_client.post(
            "/api/v1/auth/signup",
            json={"email": "new@user.com", "password": "password123", "full_name": "New"},
            headers={"User-Agent": "pytest"},
        )
        assert resp.status_code == 404
