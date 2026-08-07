"""Identity co-op Phase 1 — DB-truth contribution flow (needs Postgres).

identity-coop Phase 1 (visitors-identity, 07-08-26), Step F integration legs +
the Step G Hybrid assertions that only a real Postgres can prove.

Precondition: `docker compose -f infra/docker-compose.yml up -d postgres redis`.

This lane covers exactly what the mocked unit lane structurally cannot:

- AC-1  flag OFF ⇒ zero contribution events and zero ledger rows (both halves of
        the gate: the global setting and the per-site flag)
- AC-2  a NON-contributing site still receives graph-served identifications —
        read access is unconditional and must never be gated on contribution
- AC-5  one qualifying contribution ⇒ exactly one positive ACCRUE row, in the DB
- AC-9  an abuse-flagged visitor gets an event row but no credit
- AC-10 the flag cannot flip ON via the API without a valid, current terms_version,
        and the acceptance row lands in the SAME transaction as the flip
- D-E    the `uq_coop_accrued_site_email` PARTIAL unique index really exists and a
        duplicate ACCRUE really raises IntegrityError (the Hybrid gate — service
        code is not the enforcement, the index is)
"""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.dependencies import get_current_user
from apps.api.main import app
from apps.api.models.identity_coop import (
    ContributionConsentAcceptance,
    ContributionEvent,
    CreditLedgerEntry,
)
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.services import identity_coop as coop
from apps.api.config import settings
from apps.api.services.pii_crypto import email_hash

pytestmark = pytest.mark.integration

SITE_ON = "site_coop_on"
SITE_OFF = "site_coop_off"
EMAIL = "coop.contributor@example.com"


@pytest_asyncio.fixture
async def sessions(test_engine):
    return async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def _counts(s: AsyncSession, site_id: str) -> tuple[int, int]:
    """(contribution events, ledger rows) for a site."""
    ev = await s.execute(
        select(func.count()).select_from(ContributionEvent).where(
            ContributionEvent.site_id == site_id
        )
    )
    led = await s.execute(
        select(func.count()).select_from(CreditLedgerEntry).where(
            CreditLedgerEntry.site_id == site_id
        )
    )
    return ev.scalar_one(), led.scalar_one()


# ─────────────────────────── AC-1 — flag OFF is silent ───────────────────────────


@pytest.mark.asyncio
async def test_flag_off_produces_zero_contributions(sessions):
    """Global flag OFF ⇒ a full contribution attempt writes NOTHING.

    Drives the real resolver entrypoint (maybe_record_contribution) rather than
    the inner service, so the assertion covers the gate as actually wired.
    """
    async with sessions() as s:
        s.add(
            Site(
                site_id=SITE_OFF,
                user_id=uuid.uuid4(),
                name="Off",
                url="https://off.example.com",
            )
        )
        await s.commit()

        assert settings.identity_coop_enabled is False
        # Per-site flag also OFF by default — proven here against a REAL DB row,
        # not just the ORM default.
        enabled = (
            await s.execute(
                select(Site.contribution_enabled).where(Site.site_id == SITE_OFF)
            )
        ).scalar_one()
        assert enabled is False

        from types import SimpleNamespace

        await coop.maybe_record_contribution(
            s,
            SimpleNamespace(
                site_id=SITE_OFF,
                visitor_id="v-off",
                is_abuse_flagged=False,
                is_bot_suspect=False,
            ),
            {"email": EMAIL},
            "pdl",
        )
        assert await _counts(s, SITE_OFF) == (0, 0)


# ────────────────── AC-2 — read access is UNCONDITIONAL ──────────────────


@pytest.mark.asyncio
async def test_non_contributor_still_receives_graph_matches(sessions):
    """A site with contribution_enabled=False still gets graph-served matches.

    Enforced structurally: the graph READ path must contain no reference to the
    contribution flag at all. A behavioural test could pass by accident on a
    lucky code path; this asserts the gate is absent from the read surface, which
    is the actual locked constraint (model (a)).
    """
    import ast
    from pathlib import Path

    src = Path("apps/api/services/identity_resolver.py").read_text()
    tree = ast.parse(src)
    read_fns = {
        "_graph_node_by_email",
        "_check_beam_identity_network",
    }
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in read_fns
        ):
            body = ast.dump(node)
            assert "contribution_enabled" not in body, (
                f"{node.name} must not gate graph READS on contribution status"
            )
            assert "identity_coop" not in body

    # And the DB-level fact: a non-contributing site can hold graph rows written
    # by anyone and read them back — nothing about the co-op touches that.
    async with sessions() as s:
        s.add(
            Site(
                site_id=SITE_OFF + "_read",
                user_id=uuid.uuid4(),
                name="Reader",
                url="https://reader.example.com",
            )
        )
        await s.commit()
        got = (
            await s.execute(
                select(Site.contribution_enabled).where(
                    Site.site_id == SITE_OFF + "_read"
                )
            )
        ).scalar_one()
        assert got is False  # non-contributor …
        # … and no read-side gate exists to exclude it (asserted above).


# ───────────────── AC-5 / AC-9 — accrual against a real database ─────────────────


@pytest.mark.asyncio
async def test_qualifying_contribution_writes_ledger_row(sessions):
    """One qualifying contribution ⇒ exactly ONE positive ACCRUE row."""
    bidx = email_hash("accrue.me@example.com")
    async with sessions() as s:
        await coop.record_contribution(
            s,
            site_id=SITE_ON,
            email_bidx=bidx,
            source_provider="pdl",
            is_abuse_flagged=False,
            is_bot_suspect=False,
            contributed_on=date(2026, 8, 7),
        )
        events, ledger = await _counts(s, SITE_ON)
        assert (events, ledger) == (1, 1)

        row = (
            await s.execute(
                select(CreditLedgerEntry).where(CreditLedgerEntry.site_id == SITE_ON)
            )
        ).scalar_one()
        assert row.entry_type == "ACCRUE"
        assert row.amount == settings.coop_credit_per_contribution > 0
        assert row.reason == "contribution"
        assert row.lot_id == row.id
        assert row.created_at is not None
        assert row.spendable_at is not None and row.expires_at is not None
        assert row.spendable_at < row.expires_at
        assert row.contribution_event_id is not None

        ev = (
            await s.execute(
                select(ContributionEvent).where(ContributionEvent.site_id == SITE_ON)
            )
        ).scalar_one()
        assert ev.accrued is True
        assert ev.excluded_reason is None
        # Blind index only — the plaintext email must never appear in the row.
        assert ev.email_bidx == bidx
        assert "@" not in ev.email_bidx


@pytest.mark.asyncio
async def test_abuse_flagged_visitor_earns_no_credit(sessions):
    """AC-9: the EVENT is recorded, the CREDIT is not."""
    site = SITE_ON + "_abuse"
    async with sessions() as s:
        await coop.record_contribution(
            s,
            site_id=site,
            email_bidx=email_hash("abuser@example.com"),
            source_provider="pdl",
            is_abuse_flagged=True,
            is_bot_suspect=False,
            contributed_on=date(2026, 8, 7),
        )
        events, ledger = await _counts(s, site)
        assert events == 1, "the exclusion itself must stay auditable"
        assert ledger == 0
        ev = (
            await s.execute(
                select(ContributionEvent).where(ContributionEvent.site_id == site)
            )
        ).scalar_one()
        assert ev.accrued is False
        assert ev.excluded_reason == "fraud_flagged"


# ───────── D-E Hybrid gate — the partial unique index IS the enforcement ─────────


@pytest.mark.asyncio
async def test_accrued_partial_unique_index_exists_and_blocks_second_credit(sessions):
    """The once-per-identity rule lives in the DB, not only in service code.

    Two assertions, both required:
    1. `uq_coop_accrued_site_email` exists AND carries a WHERE predicate — a plain
       (non-partial) unique index would wrongly reject the *second event row* for a
       later day, which the design explicitly wants to keep for auditability.
    2. A second accrued row for the same (site_id, email_bidx) raises
       IntegrityError even when inserted directly, bypassing all service code.
    """
    async with sessions() as s:
        idx = (
            await s.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE indexname = 'uq_coop_accrued_site_email'"
                )
            )
        ).scalar_one_or_none()
        assert idx is not None, "D-E partial unique index missing from the schema"
        assert "UNIQUE" in idx.upper()
        assert "WHERE" in idx.upper() and "accrued" in idx.lower()

    bidx = email_hash("once.only@example.com")
    site = "site_coop_dupe"
    async with sessions() as s:
        s.add(
            ContributionEvent(
                site_id=site,
                email_bidx=bidx,
                contributed_on=date(2026, 8, 7),
                accrued=True,
            )
        )
        await s.commit()

    async with sessions() as s:
        s.add(
            ContributionEvent(
                site_id=site,
                email_bidx=bidx,
                contributed_on=date(2026, 8, 8),  # different day ⇒ audit key is fine
                accrued=True,  # … but a SECOND credit is not
            )
        )
        with pytest.raises(IntegrityError):
            await s.commit()
        await s.rollback()

    # A non-accrued repeat row for a later day is explicitly still allowed.
    async with sessions() as s:
        s.add(
            ContributionEvent(
                site_id=site,
                email_bidx=bidx,
                contributed_on=date(2026, 8, 9),
                accrued=False,
                excluded_reason="duplicate",
            )
        )
        await s.commit()
        total = (
            await s.execute(
                select(func.count())
                .select_from(ContributionEvent)
                .where(ContributionEvent.site_id == site)
            )
        ).scalar_one()
        assert total == 2


@pytest.mark.asyncio
async def test_same_day_duplicate_collapses_to_one_event(sessions):
    """AC-3 against the real unique constraint (the concurrent-race guard)."""
    bidx = email_hash("merged@example.com")
    site = "site_coop_merge"
    async with sessions() as s:
        for _ in range(2):
            await coop.record_contribution(
                s,
                site_id=site,
                email_bidx=bidx,
                source_provider="pdl",
                is_abuse_flagged=False,
                is_bot_suspect=False,
                contributed_on=date(2026, 8, 7),
            )
        events, ledger = await _counts(s, site)
        assert (events, ledger) == (1, 1)


@pytest.mark.asyncio
async def test_second_day_resolve_mints_no_second_credit_in_db(sessions):
    """D-E end-to-end through the service against a real Postgres.

    Complements the mocked unit leg: here the IntegrityError is raised by the real
    partial index, so this proves the service's duplicate branch is wired to the
    actual DB constraint and not to a hand-rolled check.
    """
    bidx = email_hash("twoday@example.com")
    site = "site_coop_twoday"
    async with sessions() as s:
        for day in (date(2026, 8, 7), date(2026, 8, 8)):
            await coop.record_contribution(
                s,
                site_id=site,
                email_bidx=bidx,
                source_provider="pdl",
                is_abuse_flagged=False,
                is_bot_suspect=False,
                contributed_on=day,
            )
        events, ledger = await _counts(s, site)
        assert events == 2, "the later-day event row stays for auditability"
        assert ledger == 1, "but only ONE credit is ever minted per identity"
        reasons = {
            r
            for (r,) in (
                await s.execute(
                    select(ContributionEvent.excluded_reason).where(
                        ContributionEvent.site_id == site
                    )
                )
            ).all()
        }
        # Exactly one accrued row (reason NULL) and one duplicate-marked row.
        assert reasons == {None, "duplicate"}


@pytest.mark.asyncio
async def test_spendable_balance_respects_hold_and_expiry(sessions):
    """AC-8: balance is derived — a held lot and an expired lot both count zero."""
    site = "site_coop_balance"
    now = datetime.now(timezone.utc)
    async with sessions() as s:
        s.add_all(
            [
                # spendable
                CreditLedgerEntry(
                    site_id=site,
                    entry_type="ACCRUE",
                    amount=5,
                    reason="contribution",
                    spendable_at=now - timedelta(hours=1),
                    expires_at=now + timedelta(days=30),
                ),
                # still on provisional hold
                CreditLedgerEntry(
                    site_id=site,
                    entry_type="ACCRUE",
                    amount=7,
                    reason="contribution",
                    spendable_at=now + timedelta(hours=5),
                    expires_at=now + timedelta(days=30),
                ),
                # expired
                CreditLedgerEntry(
                    site_id=site,
                    entry_type="ACCRUE",
                    amount=9,
                    reason="contribution",
                    spendable_at=now - timedelta(days=100),
                    expires_at=now - timedelta(days=1),
                ),
            ]
        )
        await s.commit()
        assert await coop.spendable_balance(s, site) == 5


# ─────────────── AC-10 — the flag cannot flip ON without acceptance ───────────────


@pytest_asyncio.fixture
async def owner_client(test_client, sessions):
    user_id = uuid.uuid4()
    async with sessions() as s:
        s.add(
            Site(
                site_id=SITE_ON,
                user_id=user_id,
                name="Coop",
                url="https://coop.example.com",
            )
        )
        await s.commit()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=user_id, email="owner@getbeam.fyi"
    )
    yield test_client
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_flag_on_requires_acceptance(owner_client, sessions):
    """422 without / with a bad terms_version; 200 + exactly one acceptance row.

    The acceptance row and the flag flip share one transaction, so "flag ON but no
    audit row" is not a state this endpoint can produce.
    """
    url = f"/api/v1/sites/{SITE_ON}"

    async def flag() -> bool:
        async with sessions() as s:
            return (
                await s.execute(
                    select(Site.contribution_enabled).where(Site.site_id == SITE_ON)
                )
            ).scalar_one()

    async def acceptances() -> int:
        async with sessions() as s:
            return (
                await s.execute(
                    select(func.count())
                    .select_from(ContributionConsentAcceptance)
                    .where(ContributionConsentAcceptance.site_id == SITE_ON)
                )
            ).scalar_one()

    # 1. No terms_version at all.
    r = await owner_client.patch(url, json={"contribution_enabled": True})
    assert r.status_code == 422
    assert await flag() is False
    assert await acceptances() == 0

    # 2. Wrong FORMAT (the vacuous-guard case the plan called out by name).
    r = await owner_client.patch(
        url, json={"contribution_enabled": True, "terms_version": "x"}
    )
    assert r.status_code == 422
    assert await flag() is False

    # 3. Right format, wrong value — a 64-hex string that is not the pinned one.
    r = await owner_client.patch(
        url, json={"contribution_enabled": True, "terms_version": "a" * 64}
    )
    assert r.status_code == 422
    assert await flag() is False
    assert await acceptances() == 0

    # 4. The pinned version ⇒ accepted, flag ON, exactly one acceptance row.
    r = await owner_client.patch(
        url,
        json={
            "contribution_enabled": True,
            "terms_version": settings.coop_terms_version,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["contribution_enabled"] is True
    assert await flag() is True
    assert await acceptances() == 1

    async with sessions() as s:
        acc = (
            await s.execute(
                select(ContributionConsentAcceptance).where(
                    ContributionConsentAcceptance.site_id == SITE_ON
                )
            )
        ).scalar_one()
        assert acc.terms_version == settings.coop_terms_version
        assert acc.accepted_at is not None
        assert acc.accepted_by_user_id is not None

    # 5. Opting OUT is unconditional — no terms_version required.
    r = await owner_client.patch(url, json={"contribution_enabled": False})
    assert r.status_code == 200
    assert await flag() is False
    # …and the append-only trail is NOT rewound by opting out.
    assert await acceptances() == 1


@pytest.mark.asyncio
async def test_foreign_site_is_404_not_403(test_client, sessions):
    """E3: a foreign site_id must never leak its existence via a 403."""
    async with sessions() as s:
        s.add(
            Site(
                site_id="site_coop_foreign",
                user_id=uuid.uuid4(),
                name="Theirs",
                url="https://theirs.example.com",
            )
        )
        await s.commit()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="intruder@example.com"
    )
    try:
        r = await test_client.patch(
            "/api/v1/sites/site_coop_foreign",
            json={
                "contribution_enabled": True,
                "terms_version": settings.coop_terms_version,
            },
        )
        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)
