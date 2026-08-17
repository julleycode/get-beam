"""G3 — the D4 systemic-failure abort in ``expire_lapsed_lots``. No DB.

E2 (MANDATORY, do not relax either half):

1. **Every raising leg asserts ``pytest.raises(CoopExpirySystemicFailure)``
   explicitly — never bare ``Exception``.** ``expire_lapsed_lots`` runs its
   lapsed-lot SELECT OUTSIDE any try, so a naive stub that raises on any
   ``execute`` propagates a RAW exception from there — and because
   ``CoopExpirySystemicFailure`` IS an ``Exception``, a leg written
   ``pytest.raises(Exception)`` would pass against the exact bug it forbids.
2. **The stub is shape-aware**: the lapsed-lot SELECT always succeeds; only the
   per-lot query a leg targets raises. Three execute shapes — lapsed select
   (``.all()``), ``_lot_remaining`` (``.scalar_one()``), the ``text()`` EXPIRE
   insert (``.rowcount``).
"""

import datetime as dt
import uuid

import pytest
from sqlalchemy import TextClause

from apps.api.services.identity_coop import (
    CoopExpirySystemicFailure,
    expire_lapsed_lots,
)

pytestmark = pytest.mark.unit

_PAST = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)


class _Result:
    def __init__(self, rows=None, scalar=None, rowcount=0):
        self._rows = rows or []
        self._scalar = scalar
        self.rowcount = rowcount

    def all(self):
        return self._rows

    def scalar_one(self):
        return self._scalar


class _StubSession:
    """Serves the three distinct ``execute`` shapes ``expire_lapsed_lots`` issues."""

    def __init__(self, lots, *, remaining_raises=(), insert_raises=(), zero_remaining=()):
        self.lots = lots
        self.remaining_raises = set(remaining_raises)
        self.insert_raises = set(insert_raises)
        self.zero_remaining = set(zero_remaining)
        self._served_lapsed = False
        self._idx = -1
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, stmt, params=None):
        if not self._served_lapsed:  # shape 1 — ALWAYS succeeds (E2)
            self._served_lapsed = True
            return _Result(rows=self.lots)
        if isinstance(stmt, TextClause):  # shape 3 — the EXPIRE insert
            if params["lot_id"] in self.insert_raises:
                raise RuntimeError("simulated EXPIRE insert failure")
            return _Result(rowcount=1)
        # shape 2 — _lot_remaining, one call per lot, in loop order
        self._idx += 1
        lot = self.lots[self._idx][0]
        if lot in self.remaining_raises:
            raise RuntimeError("simulated pre-attempt failure in _lot_remaining")
        return _Result(scalar=0 if lot in self.zero_remaining else 5)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def _lots(n):
    return [(uuid.uuid4(), f"site{i}", _PAST, _PAST) for i in range(n)]


async def test_g3a_one_of_three_fails_returns_two_and_does_not_raise():
    """(a) Forbids a `failures >= 1` predicate."""
    lots = _lots(3)
    db = _StubSession(lots, insert_raises={lots[1][0]})
    assert await expire_lapsed_lots(db) == 2


async def test_g3b_all_three_fail_raises_systemic_failure():
    """(b) Forbids a `failures > processed` predicate."""
    lots = _lots(3)
    db = _StubSession(lots, insert_raises={lot for lot, *_ in lots})
    with pytest.raises(CoopExpirySystemicFailure):
        await expire_lapsed_lots(db)


async def test_g3c_no_lapsed_lots_returns_zero_and_does_not_raise():
    """(c) Boundary smoke — NOT credited with catching skip-miscounting."""
    assert await expire_lapsed_lots(_StubSession([])) == 0


async def test_g3d_mixed_skip_plus_fail_must_raise():
    """(d) The ONLY skip-exclusion falsifier.

    Without `skipped` subtracted: processed=2, failures=1 -> no raise -> RED.
    """
    lots = _lots(2)
    db = _StubSession(
        lots, zero_remaining={lots[0][0]}, insert_raises={lots[1][0]}
    )
    with pytest.raises(CoopExpirySystemicFailure):
        await expire_lapsed_lots(db)


async def test_g3e_pre_attempt_failures_must_raise():
    """(e) FAIL-1 regression gate.

    With `attempted` incremented after the `remaining == 0` continue:
    attempted=0, processed=0 -> no raise -> RED. Typed assertion is load-bearing
    (a raw RuntimeError from the lapsed SELECT would satisfy a bare
    `pytest.raises(Exception)` and green this leg against the bug).
    """
    lots = _lots(2)
    db = _StubSession(lots, remaining_raises={lot for lot, *_ in lots})
    with pytest.raises(CoopExpirySystemicFailure):
        await expire_lapsed_lots(db)
