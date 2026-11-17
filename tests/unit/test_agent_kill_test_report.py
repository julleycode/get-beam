"""KTR (Fully-Automated) — assemble_kill_test_report arithmetic.

The report is a pure read-only aggregate; its four count queries run in a fixed
order (discovery, calls, param-complete, leads). We mock ``db.execute`` to return
seeded counts in that order and assert the derived rates. This proves the
arithmetic (tool_call_rate, param_fill_rate, zero-division guards) without a live
Postgres — the wild data itself is Step 5's job, not this test's.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

import apps.api.main  # noqa: F401 — registers every ORM model
from apps.api.services.agent_kill_test_report import (
    assemble_kill_test_report,
)

pytestmark = pytest.mark.unit


def _db_with_counts(discovery, calls, complete, leads):
    """A mock db whose 4 sequential execute() calls return the given scalar
    counts in the function's query order."""
    db = MagicMock()

    def _scalar_result(value):
        r = MagicMock()
        r.scalar_one.return_value = value
        return r

    db.execute = AsyncMock(
        side_effect=[
            _scalar_result(discovery),
            _scalar_result(calls),
            _scalar_result(complete),
            _scalar_result(leads),
        ]
    )
    return db


WINDOW_START = datetime(2026, 7, 1, tzinfo=timezone.utc)
WINDOW_END = WINDOW_START + timedelta(days=7)


async def test_rates_computed_from_counts():
    db = _db_with_counts(discovery=100, calls=40, complete=25, leads=8)
    report = await assemble_kill_test_report(db, "site-1", WINDOW_START, WINDOW_END)

    assert report.tool_discovery_count == 100
    assert report.tool_call_count == 40
    assert report.param_complete_count == 25
    assert report.lead_count == 8
    assert report.tool_call_rate == pytest.approx(0.40)
    assert report.param_fill_rate == pytest.approx(25 / 40)
    assert report.site_id == "site-1"


async def test_zero_discovery_no_division_error():
    db = _db_with_counts(discovery=0, calls=0, complete=0, leads=0)
    report = await assemble_kill_test_report(db, "site-1", WINDOW_START, WINDOW_END)
    # Guards return 0.0, never raise ZeroDivisionError.
    assert report.tool_call_rate == 0.0
    assert report.param_fill_rate == 0.0


async def test_calls_without_completes():
    db = _db_with_counts(discovery=10, calls=10, complete=0, leads=0)
    report = await assemble_kill_test_report(db, "site-2", WINDOW_START, WINDOW_END)
    assert report.tool_call_rate == pytest.approx(1.0)
    assert report.param_fill_rate == 0.0
