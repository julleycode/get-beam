"""WS1b: the ingest-health payload surfaces the privacy opt-out rate.

Three things are asserted, matching the assertion style of
`test_ingest_abuse_no_pii_logging.py`:

1. the response carries a `privacy_optout` block with counts + a 4-dp rate,
2. a foreign/unknown `site_id` still 404s (re-asserting `verify_site_access`
   runs BEFORE any of the new query work),
3. the new surface leaks no PII — counts and ids only (AC-9).
"""

import ast
import pathlib

import pytest
from fastapi import HTTPException

from apps.api.routers import ingest_health

pytestmark = pytest.mark.unit

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


class _Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Result:
    def __init__(self, payload):
        self._payload = payload

    def one(self):
        return self._payload

    def all(self):
        return self._payload if isinstance(self._payload, list) else []


class _FakeSession:
    """Returns canned aggregate rows for the SELECTs the endpoint runs, in
    order: event totals, visitor opt-out counts, then the two grouped
    resolution-health queries. Queries past the queue return an empty grouped
    result, so a test only has to queue what it asserts on."""

    def __init__(self, *rows):
        self._queued = list(rows)
        self.calls = 0

    async def execute(self, _stmt):
        self.calls += 1
        if not self._queued:
            return _Result([])
        return _Result(self._queued.pop(0))


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch):
    """The limiter-status helper does a live Redis round-trip; irrelevant here."""
    monkeypatch.setattr(
        ingest_health,
        "_limiter_storage_status",
        lambda: {"backend_at_process_start": "memory", "redis_live_ping": "unreachable", "degraded": True},
    )


async def _call(db, monkeypatch, site_id="site_1"):
    async def _ok(*_a, **_kw):
        return None

    monkeypatch.setattr(ingest_health, "verify_site_access", _ok)
    return await ingest_health.get_ingest_health(
        site_id=site_id, window_minutes=60, user=object(), db=db
    )


async def test_response_carries_privacy_optout(monkeypatch):
    db = _FakeSession(
        _Row(total=100, flagged=0, distinct_visitors=40),
        _Row(visitors=40, opted_out=3),
    )
    out = await _call(db, monkeypatch)

    assert out["privacy_optout"] == {"visitors": 40, "opted_out": 3, "rate": 0.075}


async def test_zero_visitors_does_not_divide_by_zero(monkeypatch):
    db = _FakeSession(
        _Row(total=0, flagged=0, distinct_visitors=0),
        _Row(visitors=0, opted_out=0),
    )
    out = await _call(db, monkeypatch)

    assert out["privacy_optout"] == {"visitors": 0, "opted_out": 0, "rate": 0.0}
    assert out["flood_signal"] == "no_traffic"


async def test_rate_rounds_to_four_places(monkeypatch):
    db = _FakeSession(
        _Row(total=10, flagged=0, distinct_visitors=3),
        _Row(visitors=3, opted_out=1),
    )
    out = await _call(db, monkeypatch)
    assert out["privacy_optout"]["rate"] == 0.3333


async def test_foreign_site_id_404s_before_any_query(monkeypatch):
    """`verify_site_access` 404s an unknown OR foreign site_id — and it must run
    first, so no visitor row is ever read for a site the caller doesn't own."""

    async def _deny(*_a, **_kw):
        raise HTTPException(status_code=404, detail="Site not found")

    monkeypatch.setattr(ingest_health, "verify_site_access", _deny)

    db = _FakeSession()
    with pytest.raises(HTTPException) as exc:
        await ingest_health.get_ingest_health(
            site_id="someone_elses_site",
            window_minutes=60,
            user=object(),
            db=db,
        )
    assert exc.value.status_code == 404
    # Not one query ran for a site the caller doesn't own.
    assert db.calls == 0


def test_optout_surface_exposes_no_pii():
    """AC-9: the opt-out addition reads counts off `visitors`, never PII."""
    src = (_REPO_ROOT / "apps/api/routers/ingest_health.py").read_text(encoding="utf-8")
    for forbidden in (
        "IdentifiedVisitor",
        ".email",
        "full_name",
        "first_name",
        "last_name",
        "ip_address",
        "user_agent",
    ):
        assert forbidden not in src, f"ingest-health surface references {forbidden}"


def test_optout_query_reads_visitors_not_events():
    """Deliberate design point: the sticky visitor-level flag is what `resolve()`
    gates on, and `events` is the largest table in the schema — no seq scan of it
    and no new index were added for this."""
    src = (_REPO_ROOT / "apps/api/routers/ingest_health.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = {
        n.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute) and n.attr == "do_not_resolve"
    }
    assert names, "expected a do_not_resolve filter in the ingest-health payload"
    assert "Event.do_not_resolve" not in src
    assert "Visitor.do_not_resolve" in src
