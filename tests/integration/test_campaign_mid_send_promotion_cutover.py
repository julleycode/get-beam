"""Identity-honesty Phase 2 / SPEC AC17 — mid-campaign promotion cutover.

The personalization gate reads ``Visitor.identity_status`` FRESH per recipient
inside the send loop. So if a human confirms a candidate part-way through a send
batch, every send AFTER the confirmation is personalized while sends BEFORE it
stay generic — and already-sent messages are never retroactively rewritten.

This drives a real ``send_campaign_emails`` batch over two candidate-tier
recipients and promotes the not-yet-sent one to ``identified`` (committed on an
independent session, exactly like the confirm-candidate endpoint would) from
inside the first dispatch.

Requires: PostgreSQL + Redis running locally (via docker-compose) — see TESTING.md.
"""

import uuid as uuidlib
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def candidate_campaign(test_db):
    """User + Site + Segment(two CANDIDATE-tier members) + active email Campaign.
    Returns (campaign_id, site_id, {email: visitor_id})."""
    from apps.api.models.campaign import Campaign
    from apps.api.models.segment import Segment, SegmentMember
    from apps.api.models.site import Site
    from apps.api.models.user import User
    from apps.api.models.visitor import IdentifiedVisitor, Visitor

    suffix = uuidlib.uuid4().hex[:8]
    site_id = f"site_{suffix}"

    user = User(email=f"cutover-{suffix}@test.com", full_name="Cutover Tester")
    test_db.add(user)
    await test_db.flush()
    test_db.add(
        Site(site_id=site_id, user_id=user.id, name="CO Site", url="https://co.example.com")
    )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    segment = Segment(site_id=site_id, name="Seg", visitor_count=2)
    test_db.add(segment)
    await test_db.flush()

    by_email: dict[str, str] = {}
    for tag, full_name in (("a", "Janet Fitzgerald"), ("b", "Marcus Blaine")):
        vid = f"vis_{tag}_{suffix}"
        email = f"lead-{tag}-{suffix}@example.com"
        by_email[email] = vid
        test_db.add(
            Visitor(
                site_id=site_id,
                visitor_id=vid,
                intent_score=90,
                first_seen=now,
                last_seen=now,
                identity_status="candidate",  # unconfirmed graph guess
            )
        )
        test_db.add(
            IdentifiedVisitor(
                site_id=site_id,
                visitor_id=vid,
                email=email,
                full_name=full_name,
                resolution_provider="rb2b",  # person-level → emailable, candidate tier
            )
        )
        test_db.add(SegmentMember(segment_id=segment.id, visitor_id=vid, site_id=site_id))

    campaign = Campaign(
        site_id=site_id,
        segment_id=segment.id,
        name="CO Campaign",
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
    return str(campaign.id), site_id, by_email


@pytest.mark.asyncio
async def test_promotion_midbatch_cuts_over_to_personalized(
    test_engine, candidate_campaign, monkeypatch
):
    from apps.api.models.campaign import Campaign, CampaignTouchpoint
    from apps.api.models.visitor import Visitor
    from apps.api.services import campaign_sender

    campaign_id, site_id, by_email = candidate_campaign
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    sent: list[tuple[str, str, str]] = []  # (to_email, subject, body_html)

    async def _fake_send(self, *, to_email, subject, body_html, **kwargs):
        sent.append((to_email, subject, body_html))
        if len(sent) == 1:
            # Mid-batch: a human confirms the OTHER candidate (independent
            # session + commit, exactly like the confirm-candidate endpoint).
            others = [v for e, v in by_email.items() if e != to_email]
            async with factory() as promo:
                await promo.execute(
                    update(Visitor)
                    .where(Visitor.site_id == site_id, Visitor.visitor_id.in_(others))
                    .values(identity_status="identified")
                )
                await promo.commit()

    async def _no_gmail(db, site_id):
        return None

    # The D5/D10 confirm-gate (candidate_outreach_enabled, default OFF) holds
    # back UNCONFIRMED graph candidates entirely. This test is about the
    # personalization cutover, not the confirm-gate, so opt in explicitly.
    monkeypatch.setattr(campaign_sender.settings, "candidate_outreach_enabled", True)
    monkeypatch.setattr(campaign_sender.EmailSender, "send", _fake_send)
    monkeypatch.setattr(campaign_sender, "resolve_sender_for_site", _no_gmail)

    async with factory() as session:
        campaign = (
            await session.execute(select(Campaign).where(Campaign.id == campaign_id))
        ).scalar_one()
        summary = await campaign_sender.send_campaign_emails(session, campaign)

    assert summary["sent"] == 2, summary
    assert len(sent) == 2

    first_email, first_subject, first_body = sent[0]
    second_email, second_subject, second_body = sent[1]

    # BEFORE the promotion: generic copy, zero guessed identity.
    assert "Hi there" == first_subject
    assert "Hello there," in first_body
    for guessed in ("Janet", "Marcus", "Fitzgerald", "Blaine"):
        assert guessed not in f"{first_subject}\n{first_body}", guessed

    # AFTER the promotion: personalized with the now-confirmed first name.
    # (fixture seeds lead-a → "Janet Fitzgerald", lead-b → "Marcus Blaine")
    expected_first_name = "Janet" if "lead-a-" in second_email else "Marcus"
    assert expected_first_name in second_subject
    assert expected_first_name in second_body

    # Already-sent message is NOT retroactively rewritten: the persisted
    # touchpoint for the first recipient still carries the generic subject.
    async with factory() as session:
        rows = (
            await session.execute(
                select(CampaignTouchpoint).where(
                    CampaignTouchpoint.campaign_id == campaign_id
                )
            )
        ).scalars().all()
    subjects = {r.visitor_id: (r.content or {}).get("subject") for r in rows}
    assert subjects[by_email[first_email]] == "Hi there"
    assert subjects[by_email[second_email]] == f"Hi {expected_first_name}"
