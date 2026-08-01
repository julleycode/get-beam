"""Unit tests for Handoff Detection H5 — server-side AI-fetch capture beacon.

Covers (all DB mocked — no live Postgres):
- record_fetch_beacon classify gating (allowlisted UA writes both rows with the
  right tier; junk UA → noop)
- multi-tenancy (unknown site_id → noop, never 403)
- token → mint-timestamp decode passed as event_time (invalid → None)
- persist_agent_fetch_event event_time → created_at (E1)
- shared-secret auth: missing / wrong / EMPTY-configured → 401 (E2 bypass guard)
- flag-off → 404 dormant

The real-DB both-row write + the AC-H5-8 non-emailability tripwire live in
tests/integration/test_agent_fetch_beacon_integration.py (Docker/PG-gated).
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from apps.api.models.database import get_db
from apps.api.routers import agents as agents_router
from apps.api.schemas.agents import FetchBeaconIn
from apps.api.services import agent_fetch_beacon as afb
from apps.api.services.agent_classifier import AgentClassification

CHATGPT_UA = "Mozilla/5.0 (compatible; ChatGPT-User/1.0; +https://openai.com/bot)"
GPTBOT_UA = "Mozilla/5.0 (compatible; GPTBot/1.0; +https://openai.com/gptbot)"


def _mint_token(secs: int) -> str:
    """Mirror apps/web mintToken: 'p' + base36(unix-seconds)."""
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    n = secs
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = digits[r] + out
    return "p" + (out or "0")


def _mock_db(site_found: bool) -> AsyncMock:
    db = AsyncMock()
    result = Mock()
    result.scalar_one_or_none = Mock(return_value="site_1" if site_found else None)
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _capture_persist(monkeypatch) -> dict:
    calls: dict = {}

    async def fake_visit(db, site_id, classification, ip_address, path):
        calls["visit"] = {"site_id": site_id, "vendor": classification.vendor, "path": path}

    async def fake_event(
        db, site_id, classification, tier, ip_address, page_path,
        event_time=None, dedup_key=None,
    ):
        calls["event"] = {
            "tier": tier,
            "event_time": event_time,
            "path": page_path,
            "dedup_key": dedup_key,
        }

    monkeypatch.setattr(afb, "persist_agent_visit", fake_visit)
    monkeypatch.setattr(afb, "persist_agent_fetch_event", fake_event)
    return calls


# ─────────────────────────── service-level: classify gating ───────────────────────────

@pytest.mark.unit
async def test_on_demand_writes_both_rows(monkeypatch):
    """AC-H5-1: on-demand fetcher UA + known site → both persist calls fire."""
    calls = _capture_persist(monkeypatch)
    db = _mock_db(site_found=True)
    result = await afb.record_fetch_beacon(
        db, FetchBeaconIn(site_id="site_1", user_agent=CHATGPT_UA, path="/pricing", token=None)
    )
    assert result == "written"
    assert calls["visit"]["vendor"] == "openai"
    assert calls["event"]["tier"] == "on-demand"
    assert calls["event"]["path"] == "/pricing"


@pytest.mark.unit
async def test_index_crawler_is_recorded_as_index_tier(monkeypatch):
    """Index-tier crawler (gptbot) is persisted, tagged index — crawlers run no
    JS so the pixel never sees them, and the tier column (not a dropped row) is
    what keeps them out of the handoff correlation sweep."""
    calls = _capture_persist(monkeypatch)
    db = _mock_db(site_found=True)
    result = await afb.record_fetch_beacon(
        db, FetchBeaconIn(site_id="site_1", user_agent=GPTBOT_UA, path="/pricing", token=None)
    )
    assert result == "written"
    assert calls["visit"]["vendor"] == "openai"
    assert calls["event"]["tier"] == "index"


@pytest.mark.unit
async def test_searchbot_is_index_tier_not_on_demand(monkeypatch):
    """OAI-SearchBot is a search-indexing crawler per OpenAI's own docs, so it
    must never be tagged on-demand — an on-demand tag would let the correlation
    sweep invent a human-behind-the-agent link from crawler traffic."""
    calls = _capture_persist(monkeypatch)
    db = _mock_db(site_found=True)
    result = await afb.record_fetch_beacon(
        db,
        FetchBeaconIn(
            site_id="site_1",
            user_agent="Mozilla/5.0 (compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot)",
            path="/pricing",
            token=None,
        ),
    )
    assert result == "written"
    assert calls["event"]["tier"] == "index"


@pytest.mark.unit
async def test_junk_ua_noop(monkeypatch):
    """AC-H5-3: junk/unknown UA → noop, nothing persisted."""
    calls = _capture_persist(monkeypatch)
    db = _mock_db(site_found=True)
    result = await afb.record_fetch_beacon(
        db, FetchBeaconIn(site_id="site_1", user_agent="curl/7.88.1", path="/pricing", token=None)
    )
    assert result == "noop"
    assert calls == {}


@pytest.mark.unit
async def test_google_is_index_tier(monkeypatch):
    """H5/E5: the conservative google vendor stays INDEX-tier (never mislabeled on-demand)."""
    calls = _capture_persist(monkeypatch)
    db = _mock_db(site_found=True)
    result = await afb.record_fetch_beacon(
        db,
        FetchBeaconIn(
            site_id="site_1", user_agent="Google-CloudVertexBot/1.0", path="/pricing", token=None
        ),
    )
    assert result == "written"
    assert calls["event"]["tier"] == "index"


@pytest.mark.unit
async def test_unknown_site_noop(monkeypatch):
    """AC-H5-6: on-demand UA but unknown/foreign site_id → noop (never 403), nothing persisted."""
    calls = _capture_persist(monkeypatch)
    db = _mock_db(site_found=False)
    result = await afb.record_fetch_beacon(
        db, FetchBeaconIn(site_id="ghost", user_agent=CHATGPT_UA, path="/pricing", token=None)
    )
    assert result == "noop"
    assert calls == {}


# ─────────────────────────── service-level: token → mint timestamp ───────────────────────────

@pytest.mark.unit
async def test_token_mint_ts(monkeypatch):
    """AC-H5-7: a valid /pricing-overview/{token} decodes to its mint datetime, passed as event_time."""
    calls = _capture_persist(monkeypatch)
    db = _mock_db(site_found=True)
    secs = 1_700_000_000
    token = _mint_token(secs)
    await afb.record_fetch_beacon(
        db,
        FetchBeaconIn(
            site_id="site_1", user_agent=CHATGPT_UA, path=f"/pricing-overview/{token}", token=token
        ),
    )
    assert calls["event"]["event_time"] == datetime.fromtimestamp(secs, tz=timezone.utc)


@pytest.mark.unit
async def test_invalid_token(monkeypatch):
    """AC-H5-7: an invalid/malformed token → event_time None (falls back to server-receive time)."""
    calls = _capture_persist(monkeypatch)
    db = _mock_db(site_found=True)
    await afb.record_fetch_beacon(
        db, FetchBeaconIn(site_id="site_1", user_agent=CHATGPT_UA, path="/pricing", token="BADTOKEN")
    )
    assert calls["event"]["event_time"] is None


@pytest.mark.unit
def test_decode_token_mint_ts_edge_cases():
    from apps.api.services.agent_fetch_beacon import decode_token_mint_ts

    assert decode_token_mint_ts(None) is None
    assert decode_token_mint_ts("") is None
    assert decode_token_mint_ts("x1abc") is None       # wrong prefix
    assert decode_token_mint_ts("p") is None            # empty body
    assert decode_token_mint_ts("pZZZ!!") is None       # non-base36 chars
    assert decode_token_mint_ts("p0") is None           # secs <= 0
    assert decode_token_mint_ts(_mint_token(1_700_000_000)) == datetime.fromtimestamp(
        1_700_000_000, tz=timezone.utc
    )


# ─────────────────────────── replay guard: dedup_key ───────────────────────────

@pytest.mark.unit
async def test_beacon_token_becomes_dedup_key(monkeypatch):
    """A re-delivered beacon carries the same mint token → the same dedup key, so
    the duplicate insert is suppressed instead of logging the fetch twice."""
    token = _mint_token(1_700_000_000)
    keys = []
    for _ in range(2):
        calls = _capture_persist(monkeypatch)
        await afb.record_fetch_beacon(
            db := _mock_db(site_found=True),
            FetchBeaconIn(
                site_id="site_1", user_agent=CHATGPT_UA, path="/pricing", token=token
            ),
        )
        assert db is not None
        keys.append(calls["event"]["dedup_key"])

    assert keys[0] is not None
    assert keys[0] == keys[1]


@pytest.mark.unit
async def test_same_token_different_agents_stay_distinct(monkeypatch):
    """A CACHED page render serves one token to every fetcher that receives it.
    The key must still separate two vendors, or the second agent's fetch would be
    silently swallowed as a replay of the first."""
    token = _mint_token(1_700_000_000)

    calls = _capture_persist(monkeypatch)
    await afb.record_fetch_beacon(
        _mock_db(site_found=True),
        FetchBeaconIn(site_id="site_1", user_agent=CHATGPT_UA, path="/p", token=token),
    )
    openai_key = calls["event"]["dedup_key"]

    calls = _capture_persist(monkeypatch)
    await afb.record_fetch_beacon(
        _mock_db(site_found=True),
        FetchBeaconIn(site_id="site_1", user_agent=GPTBOT_UA, path="/p", token=token),
    )
    assert calls["event"]["dedup_key"] != openai_key


@pytest.mark.unit
async def test_tokenless_beacon_makes_no_dedup_claim(monkeypatch):
    """No token → no retry-stable identity → None, and the row inserts freely."""
    calls = _capture_persist(monkeypatch)
    await afb.record_fetch_beacon(
        _mock_db(site_found=True),
        FetchBeaconIn(site_id="site_1", user_agent=CHATGPT_UA, path="/p", token=None),
    )
    assert calls["event"]["dedup_key"] is None


# ─────────────────────────── persistence: event_time → created_at (E1) ───────────────────────────

@pytest.mark.unit
async def test_persist_event_time_sets_created_at():
    """E1: persist_agent_fetch_event(event_time=dt) writes dt to created_at; None omits it."""
    from apps.api.services.agent_visit_persistence import persist_agent_fetch_event

    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    cls = AgentClassification("openai", "chatgpt-user", "ua-only")
    dt = datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)

    await persist_agent_fetch_event(db, "s1", cls, "on-demand", None, "/p", event_time=dt)
    stmt = db.execute.call_args[0][0]
    assert stmt.compile().params.get("created_at") == dt

    db.execute.reset_mock()
    await persist_agent_fetch_event(db, "s1", cls, "on-demand", None, "/p")
    stmt2 = db.execute.call_args[0][0]
    assert "created_at" not in stmt2.compile().params


# ─────────────────────────── router-level: auth + flag ───────────────────────────

def _beacon_client(monkeypatch, *, enabled: bool, secret: str, site_found: bool = True) -> AsyncClient:
    monkeypatch.setattr(agents_router.settings, "agent_fetch_beacon_enabled", enabled)
    monkeypatch.setattr(agents_router.settings, "beam_fetch_beacon_secret", secret)
    # Keep the write path inert for router tests — persistence itself is unit-tested above.
    monkeypatch.setattr(afb, "persist_agent_visit", AsyncMock())
    monkeypatch.setattr(afb, "persist_agent_fetch_event", AsyncMock())

    app = FastAPI()
    app.include_router(agents_router.router, prefix="/api/v1/agents")

    async def override_db():
        yield _mock_db(site_found)

    app.dependency_overrides[get_db] = override_db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


_BODY = {"site_id": "site_1", "user_agent": CHATGPT_UA, "path": "/pricing", "token": None}


@pytest.mark.unit
async def test_missing_secret_401(monkeypatch):
    """AC-H5-4: absent X-Beam-Fetch-Secret header → 401."""
    async with _beacon_client(monkeypatch, enabled=True, secret="s3cr3t") as c:
        r = await c.post("/api/v1/agents/fetch-beacon", json=_BODY)
    assert r.status_code == 401


@pytest.mark.unit
async def test_wrong_secret_401(monkeypatch):
    """AC-H5-4: mismatched secret → 401 (constant-time compare)."""
    async with _beacon_client(monkeypatch, enabled=True, secret="s3cr3t") as c:
        r = await c.post(
            "/api/v1/agents/fetch-beacon", json=_BODY, headers={"X-Beam-Fetch-Secret": "wrong"}
        )
    assert r.status_code == 401


@pytest.mark.unit
async def test_empty_secret_401(monkeypatch):
    """AC-H5-4 / E2: an EMPTY configured secret → 401 for ANY call, including an empty
    header — guarded BEFORE hmac.compare_digest (compare_digest('','') == True bypass)."""
    async with _beacon_client(monkeypatch, enabled=True, secret="") as c:
        # empty header
        r1 = await c.post(
            "/api/v1/agents/fetch-beacon", json=_BODY, headers={"X-Beam-Fetch-Secret": ""}
        )
        # no header at all
        r2 = await c.post("/api/v1/agents/fetch-beacon", json=_BODY)
        # a "guessed" non-empty header must also be rejected when unconfigured
        r3 = await c.post(
            "/api/v1/agents/fetch-beacon", json=_BODY, headers={"X-Beam-Fetch-Secret": "anything"}
        )
    assert r1.status_code == 401
    assert r2.status_code == 401
    assert r3.status_code == 401


@pytest.mark.unit
async def test_flag_off_404(monkeypatch):
    """AC-H5-5: flag off → 404 dormant (endpoint not revealed) even with a valid secret."""
    async with _beacon_client(monkeypatch, enabled=False, secret="s3cr3t") as c:
        r = await c.post(
            "/api/v1/agents/fetch-beacon", json=_BODY, headers={"X-Beam-Fetch-Secret": "s3cr3t"}
        )
    assert r.status_code == 404


@pytest.mark.unit
async def test_valid_secret_on_demand_returns_202(monkeypatch):
    """Happy path through the endpoint: valid secret + flag on + on-demand UA + known site → 202."""
    async with _beacon_client(monkeypatch, enabled=True, secret="s3cr3t", site_found=True) as c:
        r = await c.post(
            "/api/v1/agents/fetch-beacon", json=_BODY, headers={"X-Beam-Fetch-Secret": "s3cr3t"}
        )
    assert r.status_code == 202


@pytest.mark.unit
async def test_valid_secret_unknown_site_returns_204(monkeypatch):
    """AC-H5-6 at the endpoint: unknown site → 204 no-op, never 403."""
    async with _beacon_client(monkeypatch, enabled=True, secret="s3cr3t", site_found=False) as c:
        r = await c.post(
            "/api/v1/agents/fetch-beacon", json=_BODY, headers={"X-Beam-Fetch-Secret": "s3cr3t"}
        )
    assert r.status_code == 204
