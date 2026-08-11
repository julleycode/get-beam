"""Phase 2: the ingest-health payload surfaces identity-provider health.

The gap this closes: `provider_unavailable` (401/403/402 — auth or quota) writes
NO `resolution_logs` row by design, so a dead provider vanishes from that table
entirely instead of showing up as failing. On 2026-08-06 rb2b and pdl_ip_enrich
died that way and four days passed with zero identified visitors and no alert.

Assertions mirror the style of `test_ingest_abuse_no_pii_logging.py`:

1. the response carries a `resolution_health` block fusing both ledgers,
2. a foreign/unknown `site_id` still 404s before any query runs,
3. the new surface leaks no PII — counts and provider names only (AC-9).
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
    """Queued in endpoint order: event totals, opt-out counts, resolution_logs
    grouped rows, api_usage_logs grouped rows."""

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
    monkeypatch.setattr(
        ingest_health,
        "_limiter_storage_status",
        lambda: {
            "backend_at_process_start": "memory",
            "redis_live_ping": "unreachable",
            "degraded": True,
        },
    )


async def _call(db, monkeypatch, site_id="site_1"):
    async def _ok(*_a, **_kw):
        return None

    monkeypatch.setattr(ingest_health, "verify_site_access", _ok)
    return await ingest_health.get_ingest_health(
        site_id=site_id, window_minutes=1440, user=object(), db=db
    )


def _incident_session():
    """The measured 2026-08-09 shape: 34 calls, only ipinfo in resolution_logs
    (all no_match), rb2b + pdl only in api_usage_logs as unavailable."""
    return _FakeSession(
        _Row(total=100, flagged=0, distinct_visitors=34),
        _Row(visitors=34, opted_out=2),
        [_Row(provider="ipinfo", attempts=34, successes=0)],
        [
            _Row(provider="rb2b", unavailable=34),
            _Row(provider="pdl_ip_enrich", unavailable=34),
        ],
    )


async def test_response_carries_resolution_health(monkeypatch):
    out = await _call(_incident_session(), monkeypatch)
    block = out["resolution_health"]

    by_name = {p["provider"]: p for p in block["providers"]}
    assert by_name["rb2b"] == {
        "provider": "rb2b",
        "attempts": 0,
        "successes": 0,
        "unavailable": 34,
        "calls": 34,
        "unavailable_rate": 1.0,
    }
    # ipinfo answered every time — no_match is a real answer, never "unavailable".
    assert by_name["ipinfo"]["unavailable_rate"] == 0.0
    assert by_name["ipinfo"]["calls"] == 34

    assert block["total_unavailable"] == 68
    assert block["total_successes"] == 0
    assert block["total_calls"] == 102


async def test_providers_sorted_worst_first(monkeypatch):
    out = await _call(_incident_session(), monkeypatch)
    names = [p["provider"] for p in out["resolution_health"]["providers"]]
    assert names[-1] == "ipinfo"
    assert set(names[:2]) == {"rb2b", "pdl_ip_enrich"}


async def test_healthy_site_reports_zero_unavailable(monkeypatch):
    db = _FakeSession(
        _Row(total=200, flagged=0, distinct_visitors=80),
        _Row(visitors=80, opted_out=4),
        [
            _Row(provider="rb2b", attempts=80, successes=12),
            _Row(provider="ipinfo", attempts=80, successes=33),
        ],
        [],
    )
    block = (await _call(db, monkeypatch))["resolution_health"]
    assert block["total_unavailable"] == 0
    assert block["total_successes"] == 45
    assert all(p["unavailable_rate"] == 0.0 for p in block["providers"])


async def test_no_traffic_does_not_divide_by_zero(monkeypatch):
    db = _FakeSession(
        _Row(total=0, flagged=0, distinct_visitors=0),
        _Row(visitors=0, opted_out=0),
        [],
        [],
    )
    block = (await _call(db, monkeypatch))["resolution_health"]
    assert block == {
        "providers": [],
        "total_calls": 0,
        "total_successes": 0,
        "total_unavailable": 0,
    }


async def test_foreign_site_id_404s_before_any_query(monkeypatch):
    async def _deny(*_a, **_kw):
        raise HTTPException(status_code=404, detail="Site not found")

    monkeypatch.setattr(ingest_health, "verify_site_access", _deny)

    db = _FakeSession()
    with pytest.raises(HTTPException) as exc:
        await ingest_health.get_ingest_health(
            site_id="someone_elses_site", window_minutes=1440, user=object(), db=db
        )
    assert exc.value.status_code == 404
    assert db.calls == 0


async def test_payload_contains_no_pii(monkeypatch):
    """AC-9: the block is counts + provider names only — no visitor identity of
    any kind can reach the response."""
    out = await _call(_incident_session(), monkeypatch)
    block = out["resolution_health"]

    allowed_keys = {
        "provider",
        "attempts",
        "successes",
        "unavailable",
        "calls",
        "unavailable_rate",
    }
    for p in block["providers"]:
        assert set(p) == allowed_keys
        assert isinstance(p["provider"], str)
        for k in allowed_keys - {"provider"}:
            assert isinstance(p[k], (int, float))

    for forbidden in ("email", "name", "ip", "user_agent", "visitor_id"):
        assert forbidden not in {k.lower() for k in block}


def test_resolution_queries_are_window_and_tenant_scoped():
    """Both ledgers are append-heavy. The predicates must stay aligned with
    idx_resolution_logs_site_created / idx_api_usage_site_created — no new index
    was added by this work."""
    src = (_REPO_ROOT / "apps/api/routers/ingest_health.py").read_text(
        encoding="utf-8"
    )
    for needed in (
        "ResolutionLog.site_id == site_id",
        "ResolutionLog.created_at >= since",
        "ApiUsageLog.site_id == site_id",
        "ApiUsageLog.created_at >= since",
    ):
        assert needed in src, f"missing scoping predicate: {needed}"

    # No PII column may be referenced from either new query.
    tree = ast.parse(src)
    attrs = {
        n.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute)
    }
    for forbidden in ("email", "full_name", "first_name", "last_name", "ip_address"):
        assert forbidden not in attrs
