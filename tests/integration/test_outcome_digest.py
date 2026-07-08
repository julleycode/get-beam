"""Integration tests: weekly outcomes digest job.

Requires: PostgreSQL running locally (via docker-compose). The service opens
its own session against the same test database (settings.database_url).
"""

import uuid as uuidlib
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def digest_setup(test_db):
    """Two sites for one owner: one with activity this week, one dead-quiet."""
    from apps.api.models.campaign import Campaign, CampaignTouchpoint
    from apps.api.models.enrichment import EnrichmentProfile
    from apps.api.models.outcome import Conversion, ConversionGoal
    from apps.api.models.site import Site
    from apps.api.models.user import User
    from apps.api.models.visitor import IdentifiedVisitor

    user = User(email=f"digest-{uuidlib.uuid4().hex[:8]}@test.com", full_name="Digest Tester")
    test_db.add(user)
    await test_db.flush()

    active_site = f"digest_active_{uuidlib.uuid4().hex[:8]}"
    quiet_site = f"digest_quiet_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=active_site, user_id=user.id, name="Active Site", url="https://a.example.com"))
    test_db.add(Site(site_id=quiet_site, user_id=user.id, name="Quiet Site", url="https://q.example.com"))

    goal = ConversionGoal(
        id=uuidlib.uuid4(), site_id=active_site, name="Signup",
        goal_type="url_match", match_type="exact", pattern="/welcome",
    )
    test_db.add(goal)

    campaign = Campaign(
        id=uuidlib.uuid4(), site_id=active_site, name="Weekly Blast",
        campaign_type="email", status="active", plan={},
    )
    test_db.add(campaign)
    await test_db.flush()

    now = datetime.utcnow()
    for i in range(3):
        test_db.add(
            CampaignTouchpoint(
                id=uuidlib.uuid4(), campaign_id=campaign.id, visitor_id=f"dv-{i}",
                channel="email", touchpoint_order=1, status="sent",
                content={}, sent_at=now - timedelta(days=2),
                clicked_at=now - timedelta(days=1) if i == 0 else None,
            )
        )
    test_db.add(
        Conversion(
            id=uuidlib.uuid4(), site_id=active_site, goal_id=goal.id,
            visitor_id="dv-0", campaign_id=campaign.id, attribution="campaign",
            matched_by="click_link", source="url_match", value_cents=4900,
            dedupe_key=f"{goal.id}:dv-0", occurred_at=now - timedelta(hours=10),
        )
    )
    # An identified visitor this week → the digest's "who visited" section.
    test_db.add(
        IdentifiedVisitor(
            id=uuidlib.uuid4(), site_id=active_site, visitor_id="dv-0",
            email="jane@corp.example.com", full_name="Jane Digest",
            resolution_provider="form_capture",
        )
    )
    test_db.add(
        EnrichmentProfile(
            id=uuidlib.uuid4(), site_id=active_site, visitor_id="dv-0",
            job_title="VP Growth", company_name="Corp Example",
        )
    )
    await test_db.commit()
    return {"user_email": user.email, "active_site": active_site, "quiet_site": quiet_site}


class TestWeeklyDigest:
    @pytest.mark.asyncio
    async def test_sends_once_stamps_and_throttles(self, test_db, digest_setup, monkeypatch):
        from apps.api.models.site import Site
        from apps.api.services import outcome_digest
        from apps.api.services.email_sender import EmailSender

        sent_emails: list[dict] = []

        async def _fake_send(self, to_email, subject, body_html, **kwargs):
            sent_emails.append({"to": to_email, "subject": subject, "html": body_html})
            return {"status": "mocked"}

        monkeypatch.setattr(EmailSender, "send", _fake_send)

        count = await outcome_digest.send_weekly_outcome_digests()

        # Only the active site of OUR fixture is guaranteed; other tests' sites
        # may coexist in the shared DB, so filter to our recipient.
        ours = [e for e in sent_emails if e["to"] == digest_setup["user_email"]]
        assert count >= 1
        assert len(ours) == 1
        assert "Active Site" in ours[0]["subject"]
        assert "1 conversion" in ours[0]["subject"]
        assert "<strong>3</strong> campaign emails sent" in ours[0]["html"]
        assert "$49.00 attributed" in ours[0]["html"]
        # "Who visited" section: name/title/company rendered, email NEVER —
        # this report is built to be forwarded outside the account.
        assert "Who visited" in ours[0]["html"]
        assert "Jane Digest" in ours[0]["html"]
        assert "VP Growth, Corp Example" in ours[0]["html"]
        assert "jane@corp.example.com" not in ours[0]["html"]

        # Active site stamped; quiet site untouched (skipped, re-evaluated later).
        active = (
            await test_db.execute(
                select(Site).where(Site.site_id == digest_setup["active_site"])
            )
        ).scalar_one()
        quiet = (
            await test_db.execute(
                select(Site).where(Site.site_id == digest_setup["quiet_site"])
            )
        ).scalar_one()
        assert active.last_outcome_digest_sent_at is not None
        assert quiet.last_outcome_digest_sent_at is None

        # Second run inside the throttle window → nothing new for our owner.
        sent_emails.clear()
        await outcome_digest.send_weekly_outcome_digests()
        assert [e for e in sent_emails if e["to"] == digest_setup["user_email"]] == []

    @pytest.mark.asyncio
    async def test_send_failure_rolls_back_and_isolates(self, test_db, digest_setup, monkeypatch):
        from apps.api.models.site import Site
        from apps.api.services import outcome_digest
        from apps.api.services.email_sender import EmailSender

        async def _boom(self, *args, **kwargs):
            raise RuntimeError("sendgrid down")

        monkeypatch.setattr(EmailSender, "send", _boom)
        await outcome_digest.send_weekly_outcome_digests()

        active = (
            await test_db.execute(
                select(Site).where(Site.site_id == digest_setup["active_site"])
            )
        ).scalar_one()
        # Failed send must NOT stamp — the site retries next run.
        assert active.last_outcome_digest_sent_at is None
