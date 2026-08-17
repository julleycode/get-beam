"""Signal acquisition gates (engage-learning-agent Phase 1 — AC-1..AC-4).

Requires PostgreSQL + Redis running locally (conftest builds schema via
`Base.metadata.create_all`, never alembic — which is exactly why the dedupe index
has to be declared on the model and not only in the migration).

Every external call is stubbed. The X API is never contacted: `post_comment`,
`fetch_reply_mentions` and `get_tweets_metrics` all come from a `_FakeService`
monkeypatched over `get_platform_service`, following the in-repo precedent in
`test_sender_token_refresh.py`. There is no `MOCK_EXTERNAL_APIS` branch in
`services/platforms/` and inventing one would be a blast-radius expansion.

Flag handling (F8): the four sweep/poller gates are flag-gated at the sweep body,
so under flag-OFF they would assert against a deliberate no-op. They therefore
carry a skip-guard on `engage_outcome_capture_enabled` and SKIP in the flag-OFF
run, and execute in the `ENGAGE_OUTCOME_CAPTURE_ENABLED=true` run. Flag-OFF-only
evidence is vacuous, so the flag-ON run is mandatory — and `TestFlagOffControl`
asserts the no-op explicitly rather than leaving it implied.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

import apps.api.main  # noqa: F401 — registers every ORM model
from apps.api.config import settings
from apps.api.models.draft import Draft, DraftStatus, DraftType
from apps.api.models.engage_outcome import EngageOutcome
from apps.api.models.engagement_attribution import EngagementAttribution
from apps.api.models.post import Post
from apps.api.models.site import Site
from apps.api.models.social_account import Platform, SocialAccount
from apps.api.models.user import User
from apps.api.services import sender as sender_mod
from apps.api.services.encryption import encrypt_token

pytestmark = pytest.mark.integration

_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
)

# Skip-guard for the four flag-gated gates (F8 / DD-1).
requires_capture_flag = pytest.mark.skipif(
    not settings.engage_outcome_capture_enabled,
    reason=(
        "engage_outcome_capture_enabled is OFF — the sweep/poller short-circuit by "
        "design. Run with ENGAGE_OUTCOME_CAPTURE_ENABLED=true (F8)."
    ),
)

_OWN_PLATFORM_USER_ID = "999000111"
_SITE_HOST = "engage-p1.example.com"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _FakeService:
    """Controllable stand-in for a PlatformService.

    Covers the write op the send path uses plus the two NEW read ops. Mention
    dicts are RAW platform shapes carrying `author_id` and `referenced_tweets` —
    a `FeedPost` drops both, which is why the production read returns raw dicts.
    """

    def __init__(
        self,
        *,
        comment_id: str = "reply-1",
        mentions: list[dict] | None = None,
        metrics: dict[str, dict[str, int]] | None = None,
    ) -> None:
        self._comment_id = comment_id
        self._mentions = mentions or []
        self._metrics = metrics or {}
        self.posted_content: list[str] = []
        self.metrics_calls = 0

    async def post_comment(self, access_token, platform_post_id, text) -> str:
        self.posted_content.append(text)
        return self._comment_id

    async def fetch_reply_mentions(self, access_token, *, limit: int = 50):
        return list(self._mentions)

    async def get_tweets_metrics(self, access_token, ids):
        self.metrics_calls += 1
        return {k: v for k, v in self._metrics.items() if k in ids}


def _patch_platform(monkeypatch, service: _FakeService) -> None:
    """Patch every module that resolves a platform service in these paths."""
    from apps.api.services import engage_metrics_poll as poll_mod
    from apps.api.services import engage_outcome_sweep as sweep_mod
    from apps.api.services import platforms as platforms_pkg

    monkeypatch.setattr(sender_mod, "get_platform_service", lambda platform: service)
    monkeypatch.setattr(
        platforms_pkg, "get_platform_service", lambda platform: service
    )
    # The sweeps import the factory and the token helper lazily inside the body,
    # so patch at the source module rather than on the sweep module.
    monkeypatch.setattr(sweep_mod, "settings", settings, raising=False)
    monkeypatch.setattr(poll_mod, "settings", settings, raising=False)


def _patch_fresh_token(monkeypatch, token: str = "live-token") -> None:
    from apps.api.services import sync as sync_mod

    async def _fake(db, account):
        return token

    monkeypatch.setattr(sync_mod, "_get_fresh_token", _fake)


async def _seed(
    test_db,
    *,
    email_tag: str,
    site_count: int = 1,
    content: str = "thanks for the note",
    with_site_on_draft: bool = True,
    status: DraftStatus = DraftStatus.approved,
    platform_comment_id: str | None = None,
    sent_at: datetime | None = None,
    strategy: str | None = "helpful",
):
    """Create user + site(s) + social account + post + draft. Returns a bundle."""
    user = User(id=uuid.uuid4(), email=f"{email_tag}-{uuid.uuid4().hex[:6]}@test.com")
    test_db.add(user)
    await test_db.flush()

    sites: list[Site] = []
    for i in range(site_count):
        slug = f"engage_p1_{uuid.uuid4().hex[:10]}"
        site = Site(
            site_id=slug,
            user_id=user.id,
            name=f"Site {i}",
            url=f"https://{_SITE_HOST}",
        )
        test_db.add(site)
        sites.append(site)
    await test_db.flush()

    account = SocialAccount(
        id=uuid.uuid4(),
        user_id=user.id,
        platform=Platform.twitter,
        platform_user_id=_OWN_PLATFORM_USER_ID,
        username="beamowner",
        access_token=encrypt_token("access"),
        refresh_token=encrypt_token("refresh"),
        token_expires_at=_now() + timedelta(hours=2),
        is_active=True,
    )
    test_db.add(account)
    await test_db.flush()

    post = Post(
        id=uuid.uuid4(),
        social_account_id=account.id,
        platform=Platform.twitter,
        platform_post_id=f"parent-post-{uuid.uuid4().hex[:8]}",
        author_name="Someone Else",
        author_username="someone",
        content="original post",
        post_url=f"https://x.com/someone/status/parent-post-1",
        posted_at=_now(),
    )
    test_db.add(post)
    await test_db.flush()

    draft = Draft(
        id=uuid.uuid4(),
        user_id=user.id,
        type=DraftType.comment,
        post_id=post.id,
        platform=Platform.twitter,
        ai_content=content,
        status=status,
        strategy=strategy,
        site_id=sites[0].site_id if (with_site_on_draft and sites) else None,
        platform_comment_id=platform_comment_id,
        sent_at=sent_at,
    )
    test_db.add(draft)
    await test_db.commit()
    return {
        "user": user,
        "sites": sites,
        "site": sites[0] if sites else None,
        "account": account,
        "post": post,
        "draft": draft,
    }


async def _outcomes(test_db, draft_id, outcome_type: str | None = None):
    stmt = select(EngageOutcome).where(EngageOutcome.draft_id == draft_id)
    if outcome_type:
        stmt = stmt.where(EngageOutcome.outcome_type == outcome_type)
    return (await test_db.execute(stmt)).scalars().all()


def _mention(mention_id: str, replied_to: str, author_id: str) -> dict:
    return {
        "id": mention_id,
        "author_id": author_id,
        "text": "PRIVATE-BODY-SENTINEL-do-not-persist",
        "referenced_tweets": [{"type": "replied_to", "id": replied_to}],
    }


# ─────────────────────────── AC-1 + site derivation ───────────────────────────


class TestPlatformIdPersistence:
    async def test_engage_send_persists_platform_comment_id(
        self, test_db, monkeypatch
    ):
        """AC-1 — the id lands in the same transaction as status=sent."""
        bundle = await _seed(test_db, email_tag="engage-ac1")
        svc = _FakeService(comment_id="posted-reply-42")
        _patch_platform(monkeypatch, svc)

        from apps.api.services.sender import send_draft

        assert await send_draft(test_db, bundle["draft"]) is True

        await test_db.refresh(bundle["draft"])
        assert bundle["draft"].status == DraftStatus.sent
        assert bundle["draft"].platform_comment_id == "posted-reply-42"

    async def test_draft_site_id_derivation(self, test_db, monkeypatch):
        """D-O1 / N2 — 5 cases across BOTH producers.

        The manual path is the dominant user flow; a gate covering only the auto
        path would leave it unproven.
        """
        from apps.api.services.engagement_tracker import derive_draft_site_id
        from apps.api.models.visitor import Visitor

        # ── auto producer, visitor-linked → that visitor's site
        b = await _seed(test_db, email_tag="engage-derive-a", site_count=2)
        # first_seen / last_seen are NOT NULL on `visitors` (unlike
        # identified_visitors, which has neither column) — omitting them fails
        # the insert, not the assertion.
        naive_now = datetime.utcnow()
        visitor = Visitor(
            site_id=b["sites"][1].site_id,
            visitor_id=f"vis-{uuid.uuid4().hex[:8]}",
            first_seen=naive_now,
            last_seen=naive_now,
        )
        test_db.add(visitor)
        await test_db.commit()

        assert (
            await derive_draft_site_id(
                test_db, user_id=b["user"].id, visitor_id=visitor.visitor_id
            )
            == b["sites"][1].site_id
        )

        # ── auto producer, single-site user, no visitor → that site
        single = await _seed(test_db, email_tag="engage-derive-b", site_count=1)
        assert (
            await derive_draft_site_id(test_db, user_id=single["user"].id)
            == single["site"].site_id
        )

        # ── auto producer, multi-site user, no visitor → NULL
        assert await derive_draft_site_id(test_db, user_id=b["user"].id) is None

        # ── manual producer, single-site user → that site
        # The manual path never carries visitor_id, so it resolves via step 2.
        assert (
            await derive_draft_site_id(test_db, user_id=single["user"].id, visitor_id=None)
            == single["site"].site_id
        )

        # ── manual producer, multi-site user → NULL (documented limit)
        assert (
            await derive_draft_site_id(test_db, user_id=b["user"].id, visitor_id=None)
            is None
        )


# ─────────────────────────── AC-2 correlation sweep ───────────────────────────


class TestReplyBackCorrelation:
    @requires_capture_flag
    async def test_reply_received_correlation_sweep(self, test_db, monkeypatch):
        """AC-2 — an inbound reply to our reply becomes exactly one outcome row."""
        bundle = await _seed(
            test_db,
            email_tag="engage-ac2",
            status=DraftStatus.sent,
            platform_comment_id="our-reply-1",
            sent_at=_now(),
        )
        svc = _FakeService(
            mentions=[_mention("inbound-1", "our-reply-1", author_id="third-party-1")]
        )
        _patch_platform(monkeypatch, svc)
        _patch_fresh_token(monkeypatch)
        monkeypatch.setattr(settings, "engage_outcome_capture_enabled", True)

        from apps.api.services.engage_outcome_sweep import run_engage_outcome_sweep

        assert await run_engage_outcome_sweep(test_db) == 1

        rows = await _outcomes(test_db, bundle["draft"].id, "reply_received")
        assert len(rows) == 1
        assert rows[0].platform_ref == "inbound-1"
        assert rows[0].site_id == bundle["site"].site_id
        assert rows[0].strategy == "helpful"

    @requires_capture_flag
    async def test_sweep_is_idempotent_across_two_runs(self, test_db, monkeypatch):
        """G4/D-O9 — the same mocked mention read twice writes ONE row.

        This is the gate the original `observed_at` dedupe key could never pass:
        a second sweep produced a different timestamp and therefore a second row,
        double-counting every reply-back in the Phase 3a aggregate.
        """
        bundle = await _seed(
            test_db,
            email_tag="engage-idem",
            status=DraftStatus.sent,
            platform_comment_id="our-reply-2",
            sent_at=_now(),
        )
        svc = _FakeService(
            mentions=[_mention("inbound-2", "our-reply-2", author_id="third-party-2")]
        )
        _patch_platform(monkeypatch, svc)
        _patch_fresh_token(monkeypatch)
        monkeypatch.setattr(settings, "engage_outcome_capture_enabled", True)

        from apps.api.services.engage_outcome_sweep import run_engage_outcome_sweep

        first = await run_engage_outcome_sweep(test_db)
        second = await run_engage_outcome_sweep(test_db)

        assert first == 1
        assert second == 0, "second sweep must be a no-op, not a second row"
        assert len(await _outcomes(test_db, bundle["draft"].id, "reply_received")) == 1

    @requires_capture_flag
    async def test_own_account_reply_produces_no_outcome(self, test_db, monkeypatch):
        """D2d — self-inflation guard, with an in-test third-party control.

        Without the control leg a wholly broken sweep (writing nothing at all)
        would pass the exclusion assertion vacuously.
        """
        bundle = await _seed(
            test_db,
            email_tag="engage-own",
            status=DraftStatus.sent,
            platform_comment_id="our-reply-3",
            sent_at=_now(),
        )
        svc = _FakeService(
            mentions=[
                # Authored by the site's OWN connected posting account.
                _mention("inbound-own", "our-reply-3", author_id=_OWN_PLATFORM_USER_ID),
                # Control: a genuine third party on the SAME reply.
                _mention("inbound-third", "our-reply-3", author_id="outsider-7"),
            ]
        )
        _patch_platform(monkeypatch, svc)
        _patch_fresh_token(monkeypatch)
        monkeypatch.setattr(settings, "engage_outcome_capture_enabled", True)

        from apps.api.services.engage_outcome_sweep import run_engage_outcome_sweep

        await run_engage_outcome_sweep(test_db)

        rows = await _outcomes(test_db, bundle["draft"].id, "reply_received")
        refs = {r.platform_ref for r in rows}
        assert refs == {"inbound-third"}, (
            "own-account reply must be excluded AND the third-party control must "
            f"be recorded; got {refs}"
        )

    async def test_inbound_reply_body_not_persisted(self, test_db, monkeypatch):
        """F7 — the distinctive inbound body appears in ZERO columns."""
        bundle = await _seed(
            test_db,
            email_tag="engage-nobody",
            status=DraftStatus.sent,
            platform_comment_id="our-reply-4",
            sent_at=_now(),
        )
        svc = _FakeService(
            mentions=[_mention("inbound-4", "our-reply-4", author_id="third-party-4")]
        )
        _patch_platform(monkeypatch, svc)
        _patch_fresh_token(monkeypatch)
        monkeypatch.setattr(settings, "engage_outcome_capture_enabled", True)

        from apps.api.services.engage_outcome_sweep import run_engage_outcome_sweep

        await run_engage_outcome_sweep(test_db)

        rows = await _outcomes(test_db, bundle["draft"].id)
        for row in rows:
            for column in EngageOutcome.__table__.columns.keys():
                value = getattr(row, column)
                assert "PRIVATE-BODY-SENTINEL" not in str(value), (
                    f"inbound body leaked into engage_outcomes.{column}"
                )
        # The author is not recorded in any form in this phase either (N5/N6).
        assert "contact_bidx" not in EngageOutcome.__table__.columns


# ─────────────────────────── AC-3 metrics poller ───────────────────────────


class TestMetricsPoller:
    @requires_capture_flag
    async def test_reply_public_metrics_poll_records_outcomes(
        self, test_db, monkeypatch
    ):
        """AC-3 — mocked nonzero metrics land as a metrics_snapshot row."""
        bundle = await _seed(
            test_db,
            email_tag="engage-ac3",
            status=DraftStatus.sent,
            platform_comment_id="our-reply-5",
            sent_at=_now(),
        )
        svc = _FakeService(
            metrics={
                "our-reply-5": {
                    "like_count": 7,
                    "retweet_count": 3,
                    "quote_count": 1,
                    "reply_count": 2,
                }
            }
        )
        _patch_platform(monkeypatch, svc)
        _patch_fresh_token(monkeypatch)
        monkeypatch.setattr(settings, "engage_outcome_capture_enabled", True)

        from apps.api.services.engage_metrics_poll import run_engage_metrics_poll

        assert await run_engage_metrics_poll(test_db) == 1

        rows = await _outcomes(test_db, bundle["draft"].id, "metrics_snapshot")
        assert len(rows) == 1
        assert (rows[0].like_count, rows[0].retweet_count) == (7, 3)
        assert rows[0].quote_count == 1 and rows[0].reply_count == 2

    async def test_metrics_field_mapping_uses_retweet_count(
        self, test_db, monkeypatch
    ):
        """C4 anti-invention — retweet_count lands; repost_count records NOTHING.

        The negative half is the point: an invented snake_case field name is the
        exact defect that produced a 100% silent skip in the ip-org work, and only
        a fixture using the WRONG name can prove the mapping is not permissive.
        """
        good = await _seed(
            test_db,
            email_tag="engage-field-good",
            status=DraftStatus.sent,
            platform_comment_id="our-reply-6",
            sent_at=_now(),
        )
        _patch_fresh_token(monkeypatch)
        monkeypatch.setattr(settings, "engage_outcome_capture_enabled", True)

        from apps.api.services.engage_metrics_poll import run_engage_metrics_poll

        _patch_platform(
            monkeypatch,
            _FakeService(metrics={"our-reply-6": {"retweet_count": 5}}),
        )
        await run_engage_metrics_poll(test_db)
        rows = await _outcomes(test_db, good["draft"].id, "metrics_snapshot")
        assert len(rows) == 1 and rows[0].retweet_count == 5

        bad = await _seed(
            test_db,
            email_tag="engage-field-bad",
            status=DraftStatus.sent,
            platform_comment_id="our-reply-7",
            sent_at=_now(),
        )
        _patch_platform(
            monkeypatch,
            _FakeService(metrics={"our-reply-7": {"repost_count": 5}}),
        )
        await run_engage_metrics_poll(test_db)
        assert await _outcomes(test_db, bad["draft"].id, "metrics_snapshot") == []

    @requires_capture_flag
    async def test_same_day_repoll_updates_row_without_error(
        self, test_db, monkeypatch
    ):
        """N4 — latest-wins on a same-day re-poll: no IntegrityError, 1 row.

        The counters are CUMULATIVE, so a second row would double-count and an
        error would make the poller look broken. This gate is what forces the
        ON CONFLICT inference to carry the PARTIAL index predicate — without
        `index_where` asyncpg raises InvalidColumnReferenceError here.
        """
        bundle = await _seed(
            test_db,
            email_tag="engage-repoll",
            status=DraftStatus.sent,
            platform_comment_id="our-reply-8",
            sent_at=_now(),
        )
        _patch_fresh_token(monkeypatch)
        monkeypatch.setattr(settings, "engage_outcome_capture_enabled", True)

        from apps.api.services.engage_metrics_poll import run_engage_metrics_poll

        _patch_platform(
            monkeypatch,
            _FakeService(metrics={"our-reply-8": {"like_count": 1, "retweet_count": 0}}),
        )
        await run_engage_metrics_poll(test_db)

        _patch_platform(
            monkeypatch,
            _FakeService(metrics={"our-reply-8": {"like_count": 9, "retweet_count": 4}}),
        )
        await run_engage_metrics_poll(test_db)

        rows = await _outcomes(test_db, bundle["draft"].id, "metrics_snapshot")
        assert len(rows) == 1, "same-day re-poll must UPDATE, not append"
        assert (rows[0].like_count, rows[0].retweet_count) == (9, 4), (
            "counts must reflect the LATEST poll"
        )


# ─────────────────────────── AC-4 attribution mint ───────────────────────────


class TestAttributionMint:
    async def test_send_path_mints_attribution_tag_server_side(
        self, test_db, monkeypatch
    ):
        """AC-4 — tag is inside the posted content AND an attribution row exists."""
        bundle = await _seed(
            test_db,
            email_tag="engage-ac4",
            content=f"great point — more here https://{_SITE_HOST}/guide",
        )
        svc = _FakeService()
        _patch_platform(monkeypatch, svc)

        from apps.api.services.sender import send_draft

        assert await send_draft(test_db, bundle["draft"]) is True

        posted = svc.posted_content[0]
        assert "utm_source=beam_" in posted

        rows = (
            await test_db.execute(
                select(EngagementAttribution).where(
                    EngagementAttribution.draft_id == bundle["draft"].id
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].utm_tag in posted
        assert rows[0].site_id == bundle["site"].site_id

    async def test_no_link_present_records_attribution_none_and_does_not_mutate(
        self, test_db, monkeypatch
    ):
        """D-O2 — no site link means the approved content is posted byte-identical.

        A link is NEVER appended: that would post something the human never saw.
        """
        original = "thanks, that helps a lot"
        bundle = await _seed(test_db, email_tag="engage-nolink", content=original)
        svc = _FakeService()
        _patch_platform(monkeypatch, svc)

        from apps.api.services.sender import send_draft

        await send_draft(test_db, bundle["draft"])

        assert svc.posted_content == [original]
        assert (
            await test_db.execute(
                select(EngagementAttribution).where(
                    EngagementAttribution.draft_id == bundle["draft"].id
                )
            )
        ).scalars().all() == []

    async def test_foreign_host_link_is_not_rewritten(self, test_db, monkeypatch):
        """E3 — ownership is host EQUALITY, never a substring match.

        The URL below contains the site host as a substring; a substring test
        would tag an attacker-controlled domain as site-owned.
        """
        original = (
            f"see https://{_SITE_HOST}.attacker.net/x and https://other.example.org/y"
        )
        bundle = await _seed(test_db, email_tag="engage-foreign", content=original)
        svc = _FakeService()
        _patch_platform(monkeypatch, svc)

        from apps.api.services.sender import send_draft

        await send_draft(test_db, bundle["draft"])

        assert svc.posted_content == [original]
        assert "utm_source" not in svc.posted_content[0]

    async def test_at_cap_content_skips_rewrite_and_sends_original(
        self, test_db, monkeypatch
    ):
        """V7/C8 — at the 280 cap the ORIGINAL is posted, never a truncation.

        ai_reply truncates to exactly 280 at generation time using raw len(); the
        utm parameter makes the string longer and sender posts verbatim. Mutating
        past the cap would be rejected by the platform; truncating would edit a
        human-approved reply. Skipping the rewrite is the only safe option.
        """
        link = f"https://{_SITE_HOST}/g"
        filler = "x" * (280 - len(link) - 1)
        original = f"{filler} {link}"
        assert len(original) == 280

        bundle = await _seed(test_db, email_tag="engage-cap", content=original)
        svc = _FakeService()
        _patch_platform(monkeypatch, svc)

        from apps.api.services.sender import send_draft

        await send_draft(test_db, bundle["draft"])

        assert svc.posted_content == [original]
        assert "utm_source" not in svc.posted_content[0]
        assert (
            await test_db.execute(
                select(EngagementAttribution).where(
                    EngagementAttribution.draft_id == bundle["draft"].id
                )
            )
        ).scalars().all() == []

    async def test_null_site_id_skips_attribution_mint(self, test_db, monkeypatch):
        """A1c — NULL site_id fails CLOSED even with a site-owned link present."""
        bundle = await _seed(
            test_db,
            email_tag="engage-nullsite",
            content=f"more here https://{_SITE_HOST}/guide",
            with_site_on_draft=False,
        )
        assert bundle["draft"].site_id is None
        svc = _FakeService()
        _patch_platform(monkeypatch, svc)

        from apps.api.services.sender import send_draft

        assert await send_draft(test_db, bundle["draft"]) is True

        assert "utm_source" not in svc.posted_content[0]
        assert (
            await test_db.execute(
                select(EngagementAttribution).where(
                    EngagementAttribution.draft_id == bundle["draft"].id
                )
            )
        ).scalars().all() == []


class TestRoiThroughIngest:
    async def test_roi_nonzero_after_tagged_visit(
        self, test_client, test_db, monkeypatch
    ):
        """AC-4 — ROI is driven through the REAL ingest path, not a direct call.

        `attribute_visitor` had zero callers repo-wide, so calling it directly
        would prove nothing about production: the missing piece was the ingest-side
        producer. This gate posts a batch carrying a `beam_` utm_source and asserts
        both halves — the ROI counter AND the `attributed_visit` outcome row that
        Phase 3a's positive-rate depends on.
        """
        bundle = await _seed(
            test_db,
            email_tag="engage-roi",
            content=f"details https://{_SITE_HOST}/pricing",
        )
        svc = _FakeService()
        _patch_platform(monkeypatch, svc)

        from apps.api.services.sender import send_draft

        await send_draft(test_db, bundle["draft"])

        attribution = (
            await test_db.execute(
                select(EngagementAttribution).where(
                    EngagementAttribution.draft_id == bundle["draft"].id
                )
            )
        ).scalar_one()
        tag = attribution.utm_tag

        visitor_id = f"engage-roi-{uuid.uuid4().hex[:8]}"
        resp = await test_client.post(
            "/api/v1/events/ingest",
            json={
                "site_id": bundle["site"].site_id,
                "visitor_id": visitor_id,
                "events": [
                    {
                        "type": "pageview",
                        "url": f"https://{_SITE_HOST}/pricing?utm_source={tag}",
                        "page_path": "/pricing",
                        "page_title": "Pricing",
                        "user_agent": _BROWSER_UA,
                        "utm": {"source": tag},
                        "ts": "2026-08-17T00:00:00",
                    }
                ],
            },
            headers={"User-Agent": _BROWSER_UA},
        )
        assert resp.status_code == 204, resp.text

        from apps.api.services.engagement_tracker import EngagementTracker

        roi = await EngagementTracker(test_db).get_engagement_roi(bundle["user"].id)
        assert roi["new_visitors_attributed"] >= 1, roi

        rows = await _outcomes(test_db, bundle["draft"].id, "attributed_visit")
        assert len(rows) == 1
        assert rows[0].site_id == bundle["site"].site_id


# ─────────────────────────── F9 flag-OFF control ───────────────────────────


class TestFlagOffControl:
    async def test_sweep_and_poller_are_noops_when_flag_is_false(
        self, test_db, monkeypatch
    ):
        """F9 — with the flag OFF both jobs write nothing, even with data present.

        Asserted explicitly rather than inferred from the skipped gates above: a
        no-op that is only implied is not proven.
        """
        bundle = await _seed(
            test_db,
            email_tag="engage-flagoff",
            status=DraftStatus.sent,
            platform_comment_id="our-reply-9",
            sent_at=_now(),
        )
        svc = _FakeService(
            mentions=[_mention("inbound-9", "our-reply-9", author_id="third-party-9")],
            metrics={"our-reply-9": {"like_count": 4, "retweet_count": 2}},
        )
        _patch_platform(monkeypatch, svc)
        _patch_fresh_token(monkeypatch)
        monkeypatch.setattr(settings, "engage_outcome_capture_enabled", False)

        from apps.api.services.engage_metrics_poll import run_engage_metrics_poll
        from apps.api.services.engage_outcome_sweep import run_engage_outcome_sweep

        assert await run_engage_outcome_sweep(test_db) == 0
        assert await run_engage_metrics_poll(test_db) == 0
        assert await _outcomes(test_db, bundle["draft"].id) == []
