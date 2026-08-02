"""Concurrency regression: two simultaneous campaign sends must not double-email.

Idempotency used to be an application read-then-write on status='sent' with no
campaign lock. Under READ COMMITTED two concurrent /send (or /send + /start)
calls both saw no 'sent' row and both dispatched — violating the brand-critical
"never double-send" invariant. The send loop now CLAIMS a touchpoint row per
(campaign, visitor, channel) before dispatching; the unique constraint makes the
loser's flush raise IntegrityError and skip. This test drives two concurrent
send_campaign_emails calls on independent sessions and asserts exactly one
dispatch and one touchpoint row.

Requires: PostgreSQL + Redis running locally (via docker-compose).
"""

import asyncio
import uuid as uuidlib
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def seeded_campaign(test_db):
    """User + Site + Segment(one emailable member) + active email Campaign.
    Returns (campaign_id, site_id)."""
    from apps.api.models.campaign import Campaign
    from apps.api.models.segment import Segment, SegmentMember
    from apps.api.models.site import Site
    from apps.api.models.user import User
    from apps.api.models.visitor import IdentifiedVisitor, Visitor

    suffix = uuidlib.uuid4().hex[:8]
    site_id = f"site_{suffix}"
    vid = f"vis_{suffix}"

    user = User(email=f"double-send-{suffix}@test.com", full_name="DS Tester")
    test_db.add(user)
    await test_db.flush()

    test_db.add(
        Site(site_id=site_id, user_id=user.id, name="DS Site", url="https://ds.example.com")
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    test_db.add(
        Visitor(
            site_id=site_id,
            visitor_id=vid,
            intent_score=90,
            first_seen=now,
            last_seen=now,
        )
    )
    test_db.add(
        IdentifiedVisitor(
            site_id=site_id,
            visitor_id=vid,
            email=f"lead-{suffix}@example.com",
            full_name="Lead Person",
            resolution_provider="form_capture",  # first-party → emailable
        )
    )
    segment = Segment(site_id=site_id, name="Seg", visitor_count=1)
    test_db.add(segment)
    await test_db.flush()
    test_db.add(SegmentMember(segment_id=segment.id, visitor_id=vid, site_id=site_id))

    campaign = Campaign(
        site_id=site_id,
        segment_id=segment.id,
        name="DS Campaign",
        campaign_type="email",
        status="active",
        plan={
            "touchpoints": [
                {
                    "channel": "email",
                    "step": 1,
                    "subject": "Hi {{first_name}}",
                    "body": "Hello {{first_name}}, quick note.",
                }
            ]
        },
    )
    test_db.add(campaign)
    await test_db.commit()
    return str(campaign.id), site_id


async def test_concurrent_sends_dispatch_once(test_engine, seeded_campaign, monkeypatch):
    from apps.api.models.campaign import Campaign, CampaignTouchpoint
    from apps.api.services import campaign_sender

    campaign_id, _site_id = seeded_campaign

    # Count real dispatches; never touch the network. Both the Gmail resolver and
    # the SendGrid EmailSender are stubbed so the SendGrid path is taken once.
    sends: list[str] = []

    async def _fake_send(self, *, to_email, **kwargs):
        sends.append(to_email)

    async def _no_gmail(db, site_id):
        return None

    monkeypatch.setattr(campaign_sender.EmailSender, "send", _fake_send)
    monkeypatch.setattr(campaign_sender, "resolve_sender_for_site", _no_gmail)

    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async def _run():
        async with factory() as session:
            campaign = (
                await session.execute(select(Campaign).where(Campaign.id == campaign_id))
            ).scalar_one()
            return await campaign_sender.send_campaign_emails(session, campaign)

    results = await asyncio.gather(_run(), _run(), return_exceptions=True)

    # Neither concurrent call may raise (the loser handles IntegrityError itself).
    for r in results:
        assert not isinstance(r, Exception), r
    summaries = [r for r in results if isinstance(r, dict)]

    # Exactly one real email dispatched across BOTH concurrent runs.
    assert len(sends) == 1, sends
    assert sum(s["sent"] for s in summaries) == 1

    # Exactly one persisted touchpoint row, in 'sent' state.
    async with factory() as session:
        rows = (
            await session.execute(
                select(CampaignTouchpoint).where(CampaignTouchpoint.campaign_id == campaign_id)
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "sent"
