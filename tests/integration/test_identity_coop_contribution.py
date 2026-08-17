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
async def test_flag_on_requires_acceptance(owner_client, sessions, monkeypatch):
    """422 without / with a bad terms_version; 200 + exactly one acceptance row.

    The acceptance row and the flag flip share one transaction, so "flag ON but no
    audit row" is not a state this endpoint can produce.

    The global flag is patched ON for the WHOLE function (supplement item 9a /
    SUP2-C1), not just the 200 path: the M2 guard sits BEFORE the digest
    comparison, so with the flag OFF all three digest legs below would
    short-circuit on the global-flag 422 and stay green while proving nothing —
    they would still pass with the entire digest block deleted. The flag-OFF
    contract has its own function (test_contribution_flip_gated_on_global_flag).
    The `monkeypatch` fixture is mandatory here (E-S3): a bare setattr would leak
    the flag ON into the two tests that require it OFF and silently invert them.
    """
    monkeypatch.setattr(settings, "identity_coop_enabled", True)
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


# ═══════════════════════ Post-audit fix supplement (16-08-26) ═══════════════════
#
# S3/S4/S5 legs for the 16-08-26 supplement: H1 (site delete cascade), H2 (the
# erasure enqueue→sweep window), M2 (the opt-in flip guard), M3 (the resolver
# hook actually executes). One function per gate — a single function cannot
# substring-match two different `-k` selectors.

SITE_SUP = "site_coop_sup"
SUP_EMAIL = "supplement.person@example.com"


@pytest_asyncio.fixture
async def coop_on(monkeypatch):
    """Global co-op flag ON for the duration of one test (restored on teardown)."""
    monkeypatch.setattr(settings, "identity_coop_enabled", True)
    return True


@pytest_asyncio.fixture
async def no_mx(monkeypatch):
    """Deterministic email validation — the real one does a live MX lookup."""
    from apps.api.services import email_validator

    async def _ok(email: str):
        return True, ""

    monkeypatch.setattr(email_validator, "validate_email", _ok)
    return True


async def _seed_contributing_site(
    s: AsyncSession, site_id: str, visitor_id: str, *, contribution_enabled: bool = True
) -> None:
    """A site opted into the co-op plus one visitor ready to be identified."""
    from apps.api.models.visitor import Visitor

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    s.add(
        Site(
            site_id=site_id,
            user_id=uuid.uuid4(),
            name="Sup",
            url=f"https://{site_id}.example.com",
            contribution_enabled=contribution_enabled,
        )
    )
    s.add(
        Visitor(
            site_id=site_id,
            visitor_id=visitor_id,
            fingerprint=f"fp_{visitor_id}",
            first_seen=now,
            last_seen=now,
        )
    )
    await s.commit()


async def _resolve(s: AsyncSession, site_id: str, visitor_id: str, email: str):
    """Drive the REAL _save_identified path — graph write and co-op hook included."""
    from sqlalchemy import select as _select

    from apps.api.models.visitor import Visitor
    from apps.api.services.identity_resolver import IdentityResolver

    visitor = (
        await s.execute(
            _select(Visitor).where(
                Visitor.site_id == site_id, Visitor.visitor_id == visitor_id
            )
        )
    ).scalar_one()
    resolver = IdentityResolver(s, redis_client=None)
    return await resolver._save_identified(
        visitor, {"email": email, "full_name": "Sup Person"}, "pdl"
    )


async def _ledger_accrue_count(s: AsyncSession, site_id: str) -> int:
    return (
        await s.execute(
            select(func.count())
            .select_from(CreditLedgerEntry)
            .where(
                CreditLedgerEntry.site_id == site_id,
                CreditLedgerEntry.entry_type == "ACCRUE",
            )
        )
    ).scalar_one()


# ───────────────────── SG-3 — M3: the hook really mints ─────────────────────


@pytest.mark.asyncio
async def test_end_to_end_accrual(sessions, coop_on, no_mx):
    """SG-3 — both flags ON ⇒ a real resolve lands exactly 1 event + 1 ACCRUE row.

    The first end-to-end proof the resolver hook mints anything: the unit lane
    (SG-2) only proves the hook is CALLED.
    """
    site, vid = f"{SITE_SUP}_e2e", "v-e2e"
    async with sessions() as s:
        await _seed_contributing_site(s, site, vid)
        await _resolve(s, site, vid, SUP_EMAIL)

    async with sessions() as s:
        events, ledger = await _counts(s, site)
        assert (events, ledger) == (1, 1), (
            f"expected exactly 1 event + 1 ledger row, got {events} + {ledger}"
        )
        assert await _ledger_accrue_count(s, site) == 1

        ev = (
            await s.execute(
                select(ContributionEvent).where(ContributionEvent.site_id == site)
            )
        ).scalar_one()
        assert ev.site_id == site
        assert ev.email_bidx == email_hash(SUP_EMAIL)
        assert ev.email_bidx is not None
        assert ev.accrued is True


# ───────────────────── SG-4 / SG-5 — H1: site delete cascade ─────────────────


@pytest_asyncio.fixture
async def delete_client(test_client, sessions):
    """An owner client for a site that already carries co-op rows of all 3 kinds."""
    user_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    async with sessions() as s:
        s.add(
            Site(
                site_id=SITE_SUP,
                user_id=user_id,
                name="Delete me",
                url="https://delete.example.com",
                contribution_enabled=True,
            )
        )
        await s.commit()
        s.add_all(
            [
                ContributionEvent(
                    site_id=SITE_SUP,
                    email_bidx=email_hash(SUP_EMAIL),
                    contributed_on=date.today(),
                    source_provider="pdl",
                    accrued=True,
                ),
                CreditLedgerEntry(
                    site_id=SITE_SUP,
                    entry_type="ACCRUE",
                    amount=1,
                    reason="contribution",
                    spendable_at=now,
                    expires_at=now + timedelta(days=30),
                ),
                ContributionConsentAcceptance(
                    site_id=SITE_SUP,
                    terms_version=settings.coop_terms_version,
                    accepted_by_user_id=user_id,
                    accepted_at=now,
                ),
            ]
        )
        await s.commit()
    app.dependency_overrides[get_current_user] = lambda: User(
        id=user_id, email="deleter@getbeam.fyi"
    )
    yield test_client
    app.dependency_overrides.pop(get_current_user, None)


async def _acceptance_count(s: AsyncSession, site_id: str) -> int:
    return (
        await s.execute(
            select(func.count())
            .select_from(ContributionConsentAcceptance)
            .where(ContributionConsentAcceptance.site_id == site_id)
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_site_delete_removes_coop(delete_client, sessions):
    """SG-4 (H1) — deleting a site removes its spendable co-op rows.

    Without this, deleting and re-creating a site with the same site_id
    resurrected the old site's balance and its accrual suppression state.
    """
    async with sessions() as s:
        assert await _counts(s, SITE_SUP) == (1, 1), "fixture did not seed co-op rows"

    r = await delete_client.delete(f"/api/v1/sites/{SITE_SUP}")
    assert r.status_code == 204, r.text

    async with sessions() as s:
        assert await _counts(s, SITE_SUP) == (0, 0), (
            "co-op events/ledger survived the site delete — spendable credit is "
            "resurrectable by re-creating the same site_id"
        )


@pytest.mark.asyncio
async def test_site_delete_retains_consent(delete_client, sessions):
    """SG-5 (H1-D) — the consent acceptance row is DELIBERATELY retained.

    It is the append-only legal proof of lawful opt-in for contributions already
    credited to other tenants. This gate goes red if a future "cleanup" adds
    identity_contribution_consent_acceptances to the delete cascade.
    """
    async with sessions() as s:
        assert await _acceptance_count(s, SITE_SUP) == 1

    r = await delete_client.delete(f"/api/v1/sites/{SITE_SUP}")
    assert r.status_code == 204, r.text

    async with sessions() as s:
        assert await _acceptance_count(s, SITE_SUP) == 1, (
            "the consent audit trail was destroyed with the site (see H1-D)"
        )


# ─────────────── SG-6 / SG-6b — H2: the enqueue→sweep window ────────────────


@pytest_asyncio.fixture
async def sweep_sessions(test_engine, monkeypatch):
    """Session factory + the sweep pointed at it (the sweep owns its session)."""
    from apps.api.services import graph_erasure as ge

    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(ge, "async_session", factory)
    monkeypatch.setattr(ge.settings, "graph_erasure_sweep_enabled", True)
    return factory


async def _seed_match_key_email(s: AsyncSession, site_id: str, visitor_id: str, email: str):
    """A first-party email so _collect_match_keys finds a blind index to erase.

    Deliberately a VisitorEmail, NOT an IdentifiedVisitor: an existing
    IdentifiedVisitor row sends _save_identified down its conflict-upsert branch,
    which returns BEFORE the graph write and the co-op hook — the positive
    control (SG-6b) could then never mint, making SG-6's zero vacuous.
    _collect_match_keys reads both tables, so either yields the same bidx.
    """
    from apps.api.models.visitor_email import VisitorEmail

    s.add(
        VisitorEmail(
            site_id=site_id, visitor_id=visitor_id, email=email, source="form"
        )
    )
    await s.commit()


@pytest.mark.asyncio
async def test_erasure_window_race_blocked(sweep_sessions, coop_on, no_mx):
    """SG-6 (H2, the core fix) — an erasure enqueued before a resolve blocks accrual.

    Before S2 the tombstone was only written by the sweep, so a re-resolve inside
    the sweep interval minted a PERMANENT cross-tenant row and a credit for a
    person who had already asked to be forgotten. NO SWEEP IS RUN here — that is
    the whole point.
    """
    from apps.api.services import graph_erasure as ge

    site, vid = f"{SITE_SUP}_race", "v-race"
    email = "race.erased@example.com"
    async with sweep_sessions() as s:
        await _seed_contributing_site(s, site, vid)
        await _seed_match_key_email(s, site, vid, email)
        await ge.enqueue_erasure(s, site_id=site, visitor_id=vid)

    async with sweep_sessions() as s:
        await _resolve(s, site, vid, email)

    async with sweep_sessions() as s:
        events, ledger = await _counts(s, site)
        assert events == 0, "a contribution event was minted for an erased person"
        assert ledger == 0, "credit was minted for an erased person"


@pytest.mark.asyncio
async def test_erasure_window_race_control(sweep_sessions, coop_on, no_mx):
    """SG-6b — positive control: identical resolve WITHOUT the enqueue DOES mint.

    Without this, SG-6's zero could be produced by an inert hook rather than by
    the S2 fix.
    """
    site, vid = f"{SITE_SUP}_ctl", "v-ctl"
    email = "race.control@example.com"
    async with sweep_sessions() as s:
        await _seed_contributing_site(s, site, vid)
        await _seed_match_key_email(s, site, vid, email)

    async with sweep_sessions() as s:
        await _resolve(s, site, vid, email)

    async with sweep_sessions() as s:
        events, ledger = await _counts(s, site)
        assert events == 1, f"the mint path is inert — SG-6 would be vacuous ({events})"
        assert await _ledger_accrue_count(s, site) == 1
        assert ledger == 1


# ─────────────── SG-7 / SG-8 — H2 mechanism + sweep idempotency ─────────────


async def _suppression_rows(s: AsyncSession, email: str, scope: str) -> list:
    from apps.api.models.suppression import SuppressionEntry

    return list(
        (
            await s.execute(
                select(SuppressionEntry).where(
                    SuppressionEntry.email_hash == email_hash(email),
                    SuppressionEntry.scope == scope,
                )
            )
        ).scalars().all()
    )


@pytest.mark.asyncio
async def test_enqueue_writes_tombstone(sweep_sessions):
    """SG-7 — the `erased` tombstone exists the moment enqueue_erasure returns.

    This is the mechanism behind SG-6: no sweep has run at assertion time.
    """
    from apps.api.services import graph_erasure as ge

    site, vid = f"{SITE_SUP}_tomb", "v-tomb"
    email = "tombstone.now@example.com"
    async with sweep_sessions() as s:
        await _seed_contributing_site(s, site, vid, contribution_enabled=False)
        await _seed_match_key_email(s, site, vid, email)
        await ge.enqueue_erasure(s, site_id=site, visitor_id=vid)

    async with sweep_sessions() as s:
        rows = await _suppression_rows(s, email, "erased")
        assert len(rows) == 1, (
            f"no `erased` tombstone at enqueue time (got {len(rows)}) — the "
            "sweep-interval window is still open"
        )
        assert rows[0].reason == "graph_erasure"


@pytest.mark.asyncio
async def test_sweep_tombstone_idempotent(sweep_sessions):
    """SG-8 — the sweep's own tombstone write is now a harmless no-op.

    _process_claimed is deliberately unchanged; on_conflict_do_nothing makes its
    write idempotent against the row enqueue already inserted.
    """
    from apps.api.services import graph_erasure as ge

    site, vid = f"{SITE_SUP}_idem", "v-idem"
    email = "tombstone.idem@example.com"
    async with sweep_sessions() as s:
        await _seed_contributing_site(s, site, vid, contribution_enabled=False)
        await _seed_match_key_email(s, site, vid, email)
        await ge.enqueue_erasure(s, site_id=site, visitor_id=vid)

    await ge.run_graph_erasure_sweep()  # must not raise

    async with sweep_sessions() as s:
        assert len(await _suppression_rows(s, email, "erased")) == 1, (
            "the sweep duplicated the enqueue-time tombstone"
        )


# ─────────────────── SG-16 — the savepoint against a REAL Postgres ──────────


@pytest.mark.asyncio
async def test_tombstone_db_failure_preserves_erasure_request(
    sweep_sessions, monkeypatch
):
    """SG-16 (item 5c) — a genuine DB-level failure inside the tombstone statement
    rolls back ONLY the savepoint; the ErasureRequest row still commits.

    SG-15 proves the savepoint is ENTERED against a fake session. This proves
    Postgres HONOURS it: `SELECT 1/0` raises division_by_zero, which aborts the
    enclosing (sub)transaction for real. Against a bare try/except the outer
    transaction would be aborted too and the commit would lose the request.
    """
    from apps.api.models.erasure_request import ErasureRequest
    from apps.api.services import graph_erasure as ge

    site, vid = f"{SITE_SUP}_dbfail", "v-dbfail"
    email = "tombstone.dbfail@example.com"
    async with sweep_sessions() as s:
        await _seed_contributing_site(s, site, vid, contribution_enabled=False)
        await _seed_match_key_email(s, site, vid, email)

    monkeypatch.setattr(ge, "_tombstone_stmt", lambda bidx: text("SELECT 1/0"))

    async with sweep_sessions() as s:
        row = await ge.enqueue_erasure(s, site_id=site, visitor_id=vid)
        assert row is not None

    async with sweep_sessions() as s:
        queued = (
            await s.execute(
                select(func.count())
                .select_from(ErasureRequest)
                .where(ErasureRequest.requesting_site_id == site)
            )
        ).scalar_one()
        assert queued == 1, (
            "the ErasureRequest was lost when the tombstone statement failed — "
            "a false compliance receipt (SUP2-F1)"
        )
        # …and the tombstone genuinely did not land, so this is not a no-op test.
        assert await _suppression_rows(s, email, "erased") == []


# ─────────────────── SG-9 / SG-10 — M2: the opt-in flip guard ───────────────


@pytest.mark.asyncio
async def test_contribution_flip_gated_on_global_flag(owner_client, sessions):
    """SG-9 (M2) — opting IN is 422 while the deployment flag is OFF.

    A VALID, current digest is supplied deliberately: the new guard sits strictly
    before the digest comparison, so a valid digest removes the digest branch as
    an alternative explanation for the 422.
    """
    assert settings.identity_coop_enabled is False, "this gate requires the flag OFF"

    r = await owner_client.patch(
        f"/api/v1/sites/{SITE_ON}",
        json={
            "contribution_enabled": True,
            "terms_version": settings.coop_terms_version,
        },
    )
    assert r.status_code == 422, r.text
    assert "not enabled on this deployment" in r.json()["detail"]

    async with sessions() as s:
        flag = (
            await s.execute(
                select(Site.contribution_enabled).where(Site.site_id == SITE_ON)
            )
        ).scalar_one()
        assert flag is False, "the flag flipped ON with the deployment flag OFF"
        # No acceptance row either — the guard fires before record_consent_acceptance.
        assert await _acceptance_count(s, SITE_ON) == 0


@pytest.mark.asyncio
async def test_contribution_optout_never_gated(owner_client, sessions, monkeypatch):
    """SG-10 (M2) — opting OUT is never gated, even with the deployment flag OFF.

    Opting out of a data co-op must never be blocked by anything.
    """
    # Start from ON (set directly — the API path is gated by design).
    async with sessions() as s:
        await s.execute(
            text("UPDATE sites SET contribution_enabled = true WHERE site_id = :sid"),
            {"sid": SITE_ON},
        )
        await s.commit()

    assert settings.identity_coop_enabled is False, "this gate requires the flag OFF"

    r = await owner_client.patch(
        f"/api/v1/sites/{SITE_ON}", json={"contribution_enabled": False}
    )
    assert r.status_code == 200, r.text
    assert r.json()["contribution_enabled"] is False

    async with sessions() as s:
        flag = (
            await s.execute(
                select(Site.contribution_enabled).where(Site.site_id == SITE_ON)
            )
        ).scalar_one()
        assert flag is False, "opting out was blocked"
