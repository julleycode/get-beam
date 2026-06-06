"""Integration tests for Phase 5: Beam Identity Network.

Tests the beam_identity_graph table creation, upsert, and cross-customer lookup.
Requires: PostgreSQL running locally (via docker-compose).
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def test_db_with_beam(test_engine):
    """Session that also creates the beam_identity_graph table."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from apps.api.models.beam_identity import BeamIdentityNode  # noqa: F401 — register

    session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


class TestBeamIdentityModel:
    """Test beam_identity_graph table operations."""

    @pytest.mark.asyncio
    async def test_insert_identity_node(self, test_db_with_beam):
        from apps.api.models.beam_identity import BeamIdentityNode

        node = BeamIdentityNode(
            fingerprint="fp2_integration_test_001",
            email="test@company.com",
            full_name="Test User",
            confidence_score=0.90,
            source_site_id="site-alpha",
            source_provider="leadpipe",
        )
        test_db_with_beam.add(node)
        await test_db_with_beam.commit()

        result = await test_db_with_beam.execute(
            select(BeamIdentityNode).where(
                BeamIdentityNode.fingerprint == "fp2_integration_test_001"
            )
        )
        found = result.scalar_one_or_none()
        assert found is not None
        assert found.email == "test@company.com"
        assert found.full_name == "Test User"
        assert found.source_provider == "leadpipe"

    @pytest.mark.asyncio
    async def test_unique_constraint_fingerprint_email(self, test_db_with_beam):
        from apps.api.models.beam_identity import BeamIdentityNode
        from sqlalchemy.exc import IntegrityError

        fp = f"fp2_unique_{uuid.uuid4().hex[:8]}"

        node1 = BeamIdentityNode(
            fingerprint=fp,
            email="same@test.com",
            full_name="First",
            confidence_score=0.8,
            source_site_id="site-a",
            source_provider="capturify",
        )
        test_db_with_beam.add(node1)
        await test_db_with_beam.commit()

        node2 = BeamIdentityNode(
            fingerprint=fp,
            email="same@test.com",
            full_name="Duplicate",
            confidence_score=0.9,
            source_site_id="site-b",
            source_provider="rb2b",
        )
        test_db_with_beam.add(node2)
        with pytest.raises(IntegrityError):
            await test_db_with_beam.commit()
        await test_db_with_beam.rollback()

    @pytest.mark.asyncio
    async def test_same_fingerprint_different_emails_allowed(self, test_db_with_beam):
        from apps.api.models.beam_identity import BeamIdentityNode

        fp = f"fp2_multi_{uuid.uuid4().hex[:8]}"

        for email in ["alice@test.com", "bob@test.com"]:
            test_db_with_beam.add(BeamIdentityNode(
                fingerprint=fp,
                email=email,
                full_name=email.split("@")[0].title(),
                confidence_score=0.85,
                source_site_id="site-x",
                source_provider="leadpipe",
            ))
        await test_db_with_beam.commit()

        result = await test_db_with_beam.execute(
            select(BeamIdentityNode).where(BeamIdentityNode.fingerprint == fp)
        )
        nodes = result.scalars().all()
        assert len(nodes) == 2

    @pytest.mark.asyncio
    async def test_cross_site_lookup(self, test_db_with_beam):
        """Fingerprint identified on site-A should be findable for site-B."""
        from apps.api.models.beam_identity import BeamIdentityNode

        fp = f"fp2_cross_{uuid.uuid4().hex[:8]}"

        test_db_with_beam.add(BeamIdentityNode(
            fingerprint=fp,
            email="cross@company.com",
            full_name="Cross-Site User",
            confidence_score=0.92,
            source_site_id="site-alpha",
            source_provider="capturify",
        ))
        await test_db_with_beam.commit()

        # Site-beta queries by fingerprint — should find the node
        result = await test_db_with_beam.execute(
            select(BeamIdentityNode).where(
                BeamIdentityNode.fingerprint == fp,
                BeamIdentityNode.email.isnot(None),
                BeamIdentityNode.confidence_score >= 0.5,
            )
        )
        node = result.scalar_one_or_none()
        assert node is not None
        assert node.email == "cross@company.com"
        assert node.source_site_id == "site-alpha"

    @pytest.mark.asyncio
    async def test_low_confidence_filtered_out(self, test_db_with_beam):
        from apps.api.models.beam_identity import BeamIdentityNode

        fp = f"fp2_lowconf_{uuid.uuid4().hex[:8]}"

        test_db_with_beam.add(BeamIdentityNode(
            fingerprint=fp,
            email="weak@test.com",
            full_name="Weak Match",
            confidence_score=0.3,
            source_site_id="site-z",
            source_provider="rb2b",
        ))
        await test_db_with_beam.commit()

        result = await test_db_with_beam.execute(
            select(BeamIdentityNode).where(
                BeamIdentityNode.fingerprint == fp,
                BeamIdentityNode.confidence_score >= 0.5,
            )
        )
        assert result.scalar_one_or_none() is None
