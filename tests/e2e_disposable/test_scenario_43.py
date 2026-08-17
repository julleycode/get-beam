"""DE-8 — scenario 43 (decision D-E2E-1, user decision 17-08-26).

RATIONALE, RECORDED VERBATIM SO IT SURVIVES THE NEXT READER:

    The sweep DOES expire lots belonging to a site whose ``contribution_enabled``
    has since been turned OFF. Expiry is a property of THE LOT (90-day life), not
    of the site's current opt-in status. Opting out stops NEW ACCRUAL ONLY.
    Freezing existing credits on opt-out would create an
    opt-out-to-preserve-credits-forever exploit.

Both halves are asserted here: the lot expires anyway (a), and new accrual is
refused while opted out (b).
"""

import datetime as dt

import pytest
from sqlalchemy import text

from tests.e2e_disposable.conftest import expire_row_count, seed_lapsed_lot, seed_site

pytestmark = pytest.mark.disposable


async def test_de8_lot_expires_even_after_site_opts_out(
    disposable_engine, disposable_db
):
    """(a) Opting out must NOT freeze already-accrued credit."""
    from apps.api.services.identity_coop import expire_lapsed_lots

    site_id = "de8"
    await seed_site(disposable_db, site_id, contribution_enabled=True)
    past = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    async with disposable_engine.begin() as conn:
        lot = await seed_lapsed_lot(
            conn, site_id, expires_at=past, spendable_at=past - dt.timedelta(days=1)
        )
        # The site opts OUT after the credit was already accrued.
        await conn.execute(
            text("UPDATE sites SET contribution_enabled = FALSE WHERE site_id = :s"),
            {"s": site_id},
        )

    written = await expire_lapsed_lots(disposable_db)

    assert written == 1
    async with disposable_engine.connect() as conn:
        assert await expire_row_count(conn, lot) == 1, (
            "an opted-out site's lapsed lot MUST still expire — otherwise "
            "opting out preserves credits forever (the exploit D-E2E-1 forbids)"
        )


async def test_de8_opted_out_site_refuses_new_accrual(
    disposable_engine, disposable_db, coop_on, no_mx
):
    """(b) Opt-out stops NEW accrual — the complementary half."""
    from apps.api.services.identity_coop import maybe_record_contribution

    site_id = "de8b"
    await seed_site(disposable_db, site_id, contribution_enabled=False)

    class _Visitor:
        pass

    visitor = _Visitor()
    visitor.site_id = site_id
    visitor.is_abuse_flagged = False
    visitor.is_bot_suspect = False

    await maybe_record_contribution(
        disposable_db, visitor, {"email": "optout@example.test"}, "e2e"
    )

    async with disposable_engine.connect() as conn:
        ledger = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM identity_credit_ledger WHERE site_id = :s"
                ),
                {"s": site_id},
            )
        ).scalar()
        events = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM identity_contribution_events "
                    "WHERE site_id = :s"
                ),
                {"s": site_id},
            )
        ).scalar()
    assert ledger == 0, "an opted-out site must accrue no new credit"
    assert events == 0, "the per-site gate short-circuits before the event insert"


async def test_de8_opted_in_site_does_accrue(
    disposable_engine, disposable_db, coop_on, no_mx
):
    """Anti-vacuity for (b): the SAME call path DOES accrue when opted in.

    Without this, `ledger == 0` above would be green for any reason at all —
    including a broken import or a silently-swallowed exception.
    """
    from apps.api.services.identity_coop import maybe_record_contribution

    site_id = "de8c"
    await seed_site(disposable_db, site_id, contribution_enabled=True)

    class _Visitor:
        pass

    visitor = _Visitor()
    visitor.site_id = site_id
    visitor.is_abuse_flagged = False
    visitor.is_bot_suspect = False

    await maybe_record_contribution(
        disposable_db, visitor, {"email": "optin@example.test"}, "e2e"
    )

    async with disposable_engine.connect() as conn:
        ledger = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM identity_credit_ledger "
                    "WHERE site_id = :s AND entry_type = 'ACCRUE'"
                ),
                {"s": site_id},
            )
        ).scalar()
    assert ledger == 1
