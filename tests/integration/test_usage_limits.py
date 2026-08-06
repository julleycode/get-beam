"""Integration tests for apps/api/services/usage_limits.py budget meters.

AC-7 of process/features/visitors-identity/active/social-context-merge_07-08-26/:
`get_enrich_usage()` must NOT count a profile whose only write today came from
SocialIntelligence.store_social_context (which no longer stamps
social_context_updated_at). This is the real-Postgres half of BUG-2 — it also
exercises the two residuals recorded in
process/features/visitors-identity/backlog/social-context-ac7-deferred_NOTE_07-08-26.md:
  (a) NULL social_context_updated_at must be EXCLUDED by `>= today` (SQL 3VL);
  (b) _today_start() returns a NAIVE datetime while models/enrichment.py:60 is
      DateTime(timezone=True) — the comparison is resolved by an implicit cast.

Requires: PostgreSQL running locally (docker compose -f infra/docker-compose.yml
up -d postgres redis). Skipped LOUDLY (not silently) when the DB is unavailable.
"""

import uuid as uuidlib
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def usage_setup(test_client, test_db):
    from apps.api.models.enrichment import EnrichmentProfile
    from apps.api.models.site import Site
    from apps.api.models.user import User

    email = f"usage-{uuidlib.uuid4().hex[:8]}@test.com"
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "Usage Tester"},
    )
    if resp.status_code != 200:
        resp = await test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "testpass123"}
        )
    assert resp.status_code == 200, resp.text
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()

    site_id = f"usage_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(
        Site(site_id=site_id, user_id=user.id, name="Usage Site", url="https://u.example.com")
    )
    # Profile written ONLY by social-intelligence: social_context set, meter column NULL.
    test_db.add(
        EnrichmentProfile(
            site_id=site_id,
            visitor_id="v-social-only",
            enrichment_completeness=0.2,
            social_context={"recent_posts": [], "topics": ["AI/ML"], "sentiment": None},
            social_context_updated_at=None,
        )
    )
    await test_db.commit()
    return {"site_id": site_id, "user": user}


class TestEnrichUsageMeter:
    @pytest.mark.asyncio
    async def test_enrich_usage_ignores_social_intelligence_only_write(
        self, test_db, usage_setup
    ):
        """AC-7: a social-intelligence-only write consumes no deep-research slot."""
        from apps.api.services.usage_limits import get_enrich_usage

        used = await get_enrich_usage(test_db, usage_setup["site_id"])
        assert used == 0, (
            "social_context written without social_context_updated_at must not be "
            f"counted by the deep-research meter (got {used})"
        )

    @pytest.mark.asyncio
    async def test_enrich_usage_counts_a_real_deep_research_stamp(self, test_db, usage_setup):
        """Discriminating control: a genuine stamp today IS counted."""
        from apps.api.models.enrichment import EnrichmentProfile
        from apps.api.services.usage_limits import get_enrich_usage

        test_db.add(
            EnrichmentProfile(
                site_id=usage_setup["site_id"],
                visitor_id="v-deep-research",
                enrichment_completeness=0.9,
                social_context={"deep_research": {"summary": "real"}},
                social_context_updated_at=datetime.now(timezone.utc),
            )
        )
        await test_db.commit()

        assert await get_enrich_usage(test_db, usage_setup["site_id"]) == 1

    @pytest.mark.asyncio
    async def test_enrich_usage_excludes_yesterdays_stamp(self, test_db, usage_setup):
        """Residual (b) probe: the naive-vs-timestamptz day boundary holds."""
        from apps.api.models.enrichment import EnrichmentProfile
        from apps.api.services.usage_limits import get_enrich_usage

        test_db.add(
            EnrichmentProfile(
                site_id=usage_setup["site_id"],
                visitor_id="v-yesterday",
                enrichment_completeness=0.5,
                social_context={"deep_research": {"summary": "old"}},
                social_context_updated_at=datetime.now(timezone.utc) - timedelta(days=2),
            )
        )
        await test_db.commit()

        assert await get_enrich_usage(test_db, usage_setup["site_id"]) == 0
