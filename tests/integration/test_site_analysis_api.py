"""Integration tests for the onboarding site-analysis endpoints (real PG + Redis).

Mock mode: tests/conftest.py pins DATABASE_URL / REDIS_URL / GEMINI_API_KEY but
NOT MOCK_EXTERNAL_APIS (config default False), so the module-level autouse fixture
sets it explicitly. The two counter gates that MUST run mock-OFF re-apply
`monkeypatch.setattr(settings, "mock_external_apis", False)` INSIDE the test body
(function-scoped monkeypatch applied in the body runs after the autouse fixture
and wins) and assert it as their first statement — omitting that silently re-mocks
the run and makes both gates vacuous.

Patching discipline: site_analysis.py imports its collaborators with
`from ... import name`, so every patch target is the CONSUMER binding
`apps.api.services.site_analysis.<name>`.
"""

import asyncio
import uuid as uuidlib
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.config import settings
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.services import site_analysis
from apps.api.services.site_analysis import CAP_MESSAGE, FAILED_MESSAGE

pytestmark = pytest.mark.integration


def _naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "Analysis"},
    )
    if resp.status_code != 200:
        resp = await test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "testpass123"}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _mock_mode(monkeypatch):
    monkeypatch.setattr(settings, "mock_external_apis", True)
    monkeypatch.setattr(settings, "site_analysis_enabled", True)


@pytest.fixture(autouse=True)
def _task_session(monkeypatch, test_engine):
    """The background task opens its OWN session via site_analysis.async_session.
    conftest patches that symbol only in demo/events/visitors_helpers, so it must
    be pointed at the test engine here or the task would hit the real DB."""
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(site_analysis, "async_session", factory)


@pytest.fixture(autouse=True)
def _fresh_redis_singleton():
    """Rebind the app's cached Redis client to THIS test's event loop.

    The singleton is created on whichever loop first touches it; a later test on
    a new loop gets "attached to a different loop", every meter call raises, and
    get_site_analysis_usage FAILS OPEN to 0 — which silently turns every budget
    assertion green regardless of the counter. That would make the cap gates
    vacuous, so the reset is a non-vacuity requirement, not tidiness.
    """
    from apps.api.services import redis_client

    redis_client._client = None
    yield
    redis_client._client = None


@pytest.fixture(autouse=True)
def _clean_inflight():
    site_analysis._analysis_inflight.clear()
    yield
    site_analysis._analysis_inflight.clear()


async def _settle_tasks() -> None:
    """Await every fired analysis task. There is no other supported way to know a
    fire-and-forget task finished — never sleep. Copy the set first: the
    done-callback mutates it while we gather."""
    from apps.api.routers.sites import _analysis_tasks

    for _ in range(10):
        pending = list(_analysis_tasks)
        if not pending:
            break
        await asyncio.gather(*pending, return_exceptions=True)
    await asyncio.sleep(0)


@pytest_asyncio.fixture
async def owner(test_client, test_db):
    email = f"analysis-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (await test_db.execute(select(User).where(User.email == email))).scalar_one()
    return {"token": token, "user": user, "email": email}


async def _create_site(test_client, owner, name="Acme") -> str:
    resp = await test_client.post(
        "/api/v1/sites/",
        json={"name": name, "url": f"https://{uuidlib.uuid4().hex[:8]}.example.com"},
        headers=_auth(owner["token"]),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["site_id"]


async def _row(test_db, site_id: str) -> Site:
    site = (
        await test_db.execute(select(Site).where(Site.site_id == site_id))
    ).scalar_one()
    await test_db.refresh(site)
    return site


async def _counter_key(site_id: str) -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"site_analysis:count:{site_id}:{day}"


async def _read_counter(site_id: str) -> int:
    # A fresh connection per call: the app's get_redis() singleton is bound to
    # whichever loop first touched it, and reusing it here raises
    # "attached to a different loop".
    async with _redis() as r:
        raw = await r.get(await _counter_key(site_id))
        return int(raw or 0)


async def _set_counter(site_id: str, value: int) -> None:
    async with _redis() as r:
        await r.set(await _counter_key(site_id), value, ex=2 * 86400)


class _redis:
    async def __aenter__(self):
        from redis.asyncio import Redis

        self._r = Redis.from_url(settings.redis_url, decode_responses=True)
        return self._r

    async def __aexit__(self, *a):
        await self._r.aclose()
        return False


def _no_network(monkeypatch):
    """Transport-level backstop: any REAL outbound request fails the gate loudly.

    Patched at the transport, not on AsyncClient — the ASGI test_client is itself
    an httpx.AsyncClient, so patching its methods would break the test harness
    instead of guarding it.
    """

    async def _boom(*a, **kw):
        raise AssertionError("no outbound HTTP request may be issued in this gate")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _boom)


def _patch_consumer_bindings(monkeypatch):
    """Patch the CONSUMER bindings — patching site_content / gemini_client has no
    effect because site_analysis imported the names directly."""

    async def _fetch(url):
        return {
            "ok": True, "html": "", "headers": {}, "status_code": 200,
            "title": "T", "meta_description": "M", "text": "body text",
        }

    async def _gen(prompt, **kwargs):
        return "prose"

    async def _gen_json(prompt, **kwargs):
        return {"summary": "live summary", "category": "Software"}

    monkeypatch.setattr("apps.api.services.site_analysis.fetch_site_content", _fetch)
    monkeypatch.setattr("apps.api.services.site_analysis.gemini_generate", _gen)
    monkeypatch.setattr("apps.api.services.site_analysis.gemini_generate_json", _gen_json)


SAMPLE_PROFILE = {
    "summary": "Acme sells industrial widgets to manufacturers.",
    "sells": ["Widgets"],
    "category": "Manufacturing",
    "sub_industry": None,
    "icp": {
        "personas": [{"role": "Plant manager", "pain": "Downtime"}],
        "firmographics": {"size_band": "51-200", "industries": ["Industrial"], "geography": ["US"]},
    },
    "competitors": [{"name": "Rival", "domain": "rival.example", "how": "Cheaper"}],
    "meta": {"v": 1, "unknown": [], "user_edited": False},
}


# ──────────────────────────── flag + tenancy ────────────────────────────


async def test_flag_off_endpoints_404_and_no_profile_written(
    test_client, test_db, owner, monkeypatch
):
    monkeypatch.setattr(settings, "site_analysis_enabled", False)
    site_id = await _create_site(test_client, owner)
    await _settle_tasks()

    headers = _auth(owner["token"])
    assert (await test_client.get(f"/api/v1/sites/{site_id}/analysis", headers=headers)).status_code == 404
    assert (await test_client.post(f"/api/v1/sites/{site_id}/analysis", headers=headers)).status_code == 404
    put = await test_client.put(
        f"/api/v1/sites/{site_id}/analysis",
        json={"profile": SAMPLE_PROFILE},
        headers=headers,
    )
    assert put.status_code == 404

    site = await _row(test_db, site_id)
    assert site.site_profile is None
    assert site.site_profile_candidate is None
    assert site.site_profile_status is None
    assert site.site_profile_started_at is None


async def test_foreign_site_id_returns_404_never_403(test_client, owner):
    other_token = await _signup(test_client, f"other-{uuidlib.uuid4().hex[:8]}@test.com")
    site_id = await _create_site(test_client, owner)
    await _settle_tasks()
    resp = await test_client.get(
        f"/api/v1/sites/{site_id}/analysis", headers=_auth(other_token)
    )
    assert resp.status_code == 404


# ──────────────────────────── lifecycle ────────────────────────────


async def test_create_site_starts_analysis_pending(test_client, test_db, owner):
    """AC-2: create_site stamps pending and fires the run."""
    site_id = await _create_site(test_client, owner)
    site = await _row(test_db, site_id)
    assert site.site_profile_status == "pending"
    assert site.site_profile_started_at is not None
    await _settle_tasks()


async def test_full_lifecycle_pending_to_ready_persisted(test_client, test_db, owner):
    """AC-3."""
    site_id = await _create_site(test_client, owner)
    await _settle_tasks()

    resp = await test_client.get(
        f"/api/v1/sites/{site_id}/analysis", headers=_auth(owner["token"])
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["candidate"] is not None
    assert body["candidate"]["meta"]["v"] == 1
    assert body["already_running"] is False

    site = await _row(test_db, site_id)
    assert site.site_profile_candidate is not None
    assert site.site_profile is None  # only PUT writes the confirmed slot


async def test_failure_path_sets_failed(test_client, test_db, owner, monkeypatch):
    """AC-4 half one."""
    monkeypatch.setattr(settings, "mock_external_apis", False)
    _no_network(monkeypatch)

    async def _boom(url):
        raise RuntimeError("fetch exploded")

    monkeypatch.setattr("apps.api.services.site_analysis.fetch_site_content", _boom)

    site_id = await _create_site(test_client, owner)
    await _settle_tasks()

    site = await _row(test_db, site_id)
    assert site.site_profile_status == "failed"


async def test_stale_pending_derives_failed(test_client, test_db, owner):
    """AC-4 half two / R6: a backdated pending reads as failed without the row
    being mutated."""
    site_id = await _create_site(test_client, owner)
    await _settle_tasks()

    site = await _row(test_db, site_id)
    site.site_profile_status = "pending"
    site.site_profile_started_at = _naive_utcnow() - timedelta(
        seconds=settings.site_analysis_stale_seconds + 60
    )
    await test_db.commit()

    resp = await test_client.get(
        f"/api/v1/sites/{site_id}/analysis", headers=_auth(owner["token"])
    )
    assert resp.json()["status"] == "failed"

    site = await _row(test_db, site_id)
    assert site.site_profile_status == "pending"  # read never mutates


# ──────────────────────────── PUT ────────────────────────────


async def test_put_edited_profile_overwrites_ai_values(test_client, test_db, owner):
    """AC-5: what is persisted is the USER's version, not the raw AI output."""
    site_id = await _create_site(test_client, owner)
    await _settle_tasks()

    edited = dict(SAMPLE_PROFILE, summary="MY OWN WORDS about the business.")
    resp = await test_client.put(
        f"/api/v1/sites/{site_id}/analysis",
        json={"profile": edited},
        headers=_auth(owner["token"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["profile"]["summary"] == "MY OWN WORDS about the business."
    assert body["candidate"] is None  # promoted

    site = await _row(test_db, site_id)
    assert site.site_profile["summary"] == "MY OWN WORDS about the business."
    assert site.site_profile["meta"]["user_edited"] is True
    assert site.site_profile_candidate is None


async def test_confirm_fills_empty_description(test_client, test_db, owner):
    """AC-6 branch one."""
    site_id = await _create_site(test_client, owner)
    await _settle_tasks()

    await test_client.put(
        f"/api/v1/sites/{site_id}/analysis",
        json={"profile": SAMPLE_PROFILE, "apply_description": True, "apply_category": True},
        headers=_auth(owner["token"]),
    )
    site = await _row(test_db, site_id)
    assert site.description == SAMPLE_PROFILE["summary"]
    assert site.category == "Manufacturing"


async def test_confirm_preserves_user_typed_description(test_client, test_db, owner):
    """AC-6 branch two: the server honors the boolean literally and never infers."""
    site_id = await _create_site(test_client, owner)
    await _settle_tasks()

    site = await _row(test_db, site_id)
    site.description = "I typed this myself"
    await test_db.commit()

    await test_client.put(
        f"/api/v1/sites/{site_id}/analysis",
        json={"profile": SAMPLE_PROFILE, "apply_description": False},
        headers=_auth(owner["token"]),
    )
    site = await _row(test_db, site_id)
    assert site.description == "I typed this myself"


async def test_put_promote_false_dismisses_candidate_only(test_client, test_db, owner):
    """VC9: dismiss NULLs the candidate and leaves everything else byte-identical."""
    site_id = await _create_site(test_client, owner)
    await _settle_tasks()

    site = await _row(test_db, site_id)
    site.site_profile = {"summary": "CONFIRMED EARLIER"}
    site.description = "kept"
    site.category = "KeptCat"
    await test_db.commit()
    before = (
        dict(site.site_profile),
        site.site_profile_status,
        site.site_profile_started_at,
        site.site_profile_analyzed_at,
        site.description,
        site.category,
    )

    resp = await test_client.put(
        f"/api/v1/sites/{site_id}/analysis",
        json={"profile": SAMPLE_PROFILE, "promote": False, "apply_description": True},
        headers=_auth(owner["token"]),
    )
    assert resp.status_code == 200

    site = await _row(test_db, site_id)
    assert site.site_profile_candidate is None
    assert (
        dict(site.site_profile),
        site.site_profile_status,
        site.site_profile_started_at,
        site.site_profile_analyzed_at,
        site.description,
        site.category,
    ) == before


async def test_put_during_pending_preserves_pending_status(test_client, test_db, owner):
    """C18/VC4: a PUT mid-run must not erase the state the stale derivation and
    the cross-process in-flight check both read."""
    site_id = await _create_site(test_client, owner)
    await _settle_tasks()

    site = await _row(test_db, site_id)
    site.site_profile_status = "pending"
    site.site_profile_started_at = _naive_utcnow()
    site.site_profile_candidate = {"summary": "in flight"}
    await test_db.commit()
    started_before = site.site_profile_started_at

    resp = await test_client.put(
        f"/api/v1/sites/{site_id}/analysis",
        json={"profile": SAMPLE_PROFILE},
        headers=_auth(owner["token"]),
    )
    assert resp.status_code == 200

    site = await _row(test_db, site_id)
    assert site.site_profile is not None  # confirmed slot still written
    assert site.site_profile_candidate is None
    assert site.site_profile_status == "pending"  # NOT downgraded
    assert site.site_profile_started_at == started_before

    # A concurrent POST still sees the run.
    post = await test_client.post(
        f"/api/v1/sites/{site_id}/analysis", headers=_auth(owner["token"])
    )
    assert post.json()["already_running"] is True


async def test_put_with_no_candidate_is_allowed(test_client, test_db, owner):
    """C18/VC4: the edit-the-confirmed-profile path, legal at status "none"."""
    site_id = await _create_site(test_client, owner)
    await _settle_tasks()

    site = await _row(test_db, site_id)
    site.site_profile_candidate = None
    site.site_profile_status = None
    await test_db.commit()
    analyzed_before = site.site_profile_analyzed_at

    resp = await test_client.put(
        f"/api/v1/sites/{site_id}/analysis",
        json={"profile": SAMPLE_PROFILE},
        headers=_auth(owner["token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"

    site = await _row(test_db, site_id)
    assert site.site_profile["category"] == "Manufacturing"
    # PUT never stamps analyzed_at — it means "when the run that produced the
    # candidate finished" and has exactly one writer, the task.
    assert site.site_profile_analyzed_at == analyzed_before


async def test_get_returns_candidate_and_confirmed_separately(
    test_client, test_db, owner
):
    """V1: two distinct slots on the wire."""
    site_id = await _create_site(test_client, owner)
    await _settle_tasks()

    site = await _row(test_db, site_id)
    site.site_profile = dict(SAMPLE_PROFILE, summary="CONFIRMED SLOT")
    site.site_profile_candidate = dict(SAMPLE_PROFILE, summary="CANDIDATE SLOT")
    await test_db.commit()

    body = (
        await test_client.get(
            f"/api/v1/sites/{site_id}/analysis", headers=_auth(owner["token"])
        )
    ).json()
    assert body["profile"]["summary"] == "CONFIRMED SLOT"
    assert body["candidate"]["summary"] == "CANDIDATE SLOT"


# ──────────────────────────── re-run + budget ────────────────────────────


async def test_rerun_lifecycle_preserves_prior_profile_until_confirm(
    test_client, test_db, owner
):
    """AC-8: the confirmed profile is byte-identical across a re-run."""
    site_id = await _create_site(test_client, owner)
    await _settle_tasks()

    await test_client.put(
        f"/api/v1/sites/{site_id}/analysis",
        json={"profile": SAMPLE_PROFILE},
        headers=_auth(owner["token"]),
    )
    site = await _row(test_db, site_id)
    confirmed_before = dict(site.site_profile)

    resp = await test_client.post(
        f"/api/v1/sites/{site_id}/analysis", headers=_auth(owner["token"])
    )
    assert resp.status_code == 200
    await _settle_tasks()

    site = await _row(test_db, site_id)
    assert dict(site.site_profile) == confirmed_before  # untouched by the re-run
    assert site.site_profile_candidate is not None  # new output waits for review

    await test_client.put(
        f"/api/v1/sites/{site_id}/analysis",
        json={"profile": dict(SAMPLE_PROFILE, summary="PROMOTED")},
        headers=_auth(owner["token"]),
    )
    site = await _row(test_db, site_id)
    assert site.site_profile["summary"] == "PROMOTED"
    assert site.site_profile_candidate is None


async def test_concurrent_post_while_pending_returns_already_running(
    test_client, test_db, owner
):
    """V4 + C23: the second POST is refused, and after the run settles a further
    POST is ACCEPTED — the only gate proving the done-callback discard ran, i.e.
    that the fire path went through _fire_site_analysis and not a bare
    asyncio.create_task."""
    site_id = await _create_site(test_client, owner)
    await _settle_tasks()

    site = await _row(test_db, site_id)
    site.site_profile_status = "pending"
    site.site_profile_started_at = _naive_utcnow()
    await test_db.commit()
    started_before = site.site_profile_started_at
    counter_before = await _read_counter(site_id)

    resp = await test_client.post(
        f"/api/v1/sites/{site_id}/analysis", headers=_auth(owner["token"])
    )
    assert resp.status_code == 200
    assert resp.json()["already_running"] is True

    site = await _row(test_db, site_id)
    assert site.site_profile_started_at == started_before  # never re-armed
    assert await _read_counter(site_id) == counter_before  # never incremented

    # Settle, then a further POST must be accepted again.
    site.site_profile_status = "ready"
    await test_db.commit()
    await _settle_tasks()

    again = await test_client.post(
        f"/api/v1/sites/{site_id}/analysis", headers=_auth(owner["token"])
    )
    assert again.status_code == 200
    assert again.json()["already_running"] is False
    await _settle_tasks()


async def test_budget_exhaustion_returns_capped_response_no_extra_runs(
    test_client, test_db, owner
):
    """AC-10 per-layer: HTTP 200, allowed=false, profile untouched, no run."""
    site_id = await _create_site(test_client, owner)
    await _settle_tasks()

    site = await _row(test_db, site_id)
    site.site_profile = dict(SAMPLE_PROFILE)
    site.site_profile_status = "ready"
    await test_db.commit()
    before = dict(site.site_profile)

    await _set_counter(site_id, settings.site_analysis_daily_budget)

    resp = await test_client.post(
        f"/api/v1/sites/{site_id}/analysis", headers=_auth(owner["token"])
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["budget"]["allowed"] is False
    assert body["profile"] == before or body["profile"]["summary"] == before["summary"]

    await _settle_tasks()
    site = await _row(test_db, site_id)
    assert dict(site.site_profile) == before


async def test_budget_denied_run_does_not_linger_pending(test_client, test_db, owner):
    """C15 + VF1: a denied task run is terminal immediately, and the CAP copy
    comes back on the GET RESPONSE — nothing persists it."""
    site_id = await _create_site(test_client, owner)
    await _settle_tasks()

    await _set_counter(site_id, settings.site_analysis_daily_budget)

    # Drive the task directly (the endpoint would refuse before firing) with mock
    # OFF so the budget check is actually reached.
    site = await _row(test_db, site_id)
    site.site_profile_status = "pending"
    site.site_profile_started_at = _naive_utcnow()
    await test_db.commit()

    orig_mock = settings.mock_external_apis
    settings.mock_external_apis = False
    try:
        await site_analysis.run_site_analysis(site_id)
    finally:
        settings.mock_external_apis = orig_mock

    site = await _row(test_db, site_id)
    assert site.site_profile_status == "failed"  # not left pending for 180 s

    body = (
        await test_client.get(
            f"/api/v1/sites/{site_id}/analysis", headers=_auth(owner["token"])
        )
    ).json()
    assert body["status"] == "failed"
    assert body["message"] == CAP_MESSAGE


async def test_budget_counter_delta_is_one_per_post_cycle(
    test_client, test_db, owner, monkeypatch
):
    """AC-10 end to end (F5). Five mandatory hardenings, all present:
    (a) consumer bindings patched by name, (b) transport raises on any other
    outbound request, (c) the delta window opens AFTER the create-time task has
    settled, (d) awaited via the router's own _analysis_tasks handle, never a
    sleep, (e) terminal `ready` asserted alongside delta == 1."""
    monkeypatch.setattr(settings, "mock_external_apis", False)
    assert settings.mock_external_apis is False  # E20: first statement, non-vacuity

    _no_network(monkeypatch)  # (b)
    _patch_consumer_bindings(monkeypatch)  # (a)

    site_id = await _create_site(test_client, owner)
    await _settle_tasks()  # (c) let the create-time run finish first

    before = await _read_counter(site_id)

    resp = await test_client.post(
        f"/api/v1/sites/{site_id}/analysis", headers=_auth(owner["token"])
    )
    assert resp.status_code == 200
    assert resp.json()["already_running"] is False
    await _settle_tasks()  # (d)

    assert await _read_counter(site_id) - before == 1

    site = await _row(test_db, site_id)
    assert site.site_profile_status == "ready"  # (e) not just the arithmetic
    assert site.site_profile_candidate["summary"] == "live summary"


async def test_message_derivation_truth_table(test_client, test_db, owner):
    """C25/E21 — the gate that MUST fail against a pre-C21 status-switch reading.

    Asserts all four (allowed, derived-status) cells of the precedence. Cell (i),
    the cap copy on a NON-failed row, is the whole point: a status-switch
    implementation returns null there and ships a capped POST and a disabled
    Analyze button with no copy at all, while passing every other message gate
    (they all sit on a `failed` row).

    `allowed` is driven by pre-setting the raw Redis counter; status by writing
    the sites row directly. Every assertion is on the RESPONSE, never on the DB
    row — nothing persists a message.
    """
    site_id = await _create_site(test_client, owner)
    await _settle_tasks()
    headers = _auth(owner["token"])
    url = f"/api/v1/sites/{site_id}/analysis"

    async def _set_status(status: str) -> None:
        site = await _row(test_db, site_id)
        site.site_profile_status = status
        site.site_profile_started_at = _naive_utcnow()
        await test_db.commit()

    exhausted = settings.site_analysis_daily_budget

    # (i) allowed=false + ready  => cap copy, on the GET *and* the POST body.
    await _set_status("ready")
    await _set_counter(site_id, exhausted)
    get_ready = (await test_client.get(url, headers=headers)).json()
    assert get_ready["status"] == "ready"
    assert get_ready["budget"]["allowed"] is False
    assert get_ready["message"] == CAP_MESSAGE

    post_capped = (await test_client.post(url, headers=headers)).json()
    assert post_capped["budget"]["allowed"] is False
    assert post_capped["message"] == CAP_MESSAGE

    # (i, cont.) the same on a never-analyzed row — the disabled Analyze button.
    site = await _row(test_db, site_id)
    site.site_profile_status = None
    site.site_profile_started_at = None
    await test_db.commit()
    get_none = (await test_client.get(url, headers=headers)).json()
    assert get_none["status"] == "none"
    assert get_none["message"] == CAP_MESSAGE

    # (ii) allowed=false + failed => cap copy.
    await _set_status("failed")
    assert (await test_client.get(url, headers=headers)).json()["message"] == CAP_MESSAGE

    # (iii) allowed=true + failed => the generic failure copy.
    await _set_counter(site_id, 0)
    get_failed = (await test_client.get(url, headers=headers)).json()
    assert get_failed["budget"]["allowed"] is True
    assert get_failed["message"] == FAILED_MESSAGE

    # (iv) allowed=true + ready => null.
    await _set_status("ready")
    get_ok = (await test_client.get(url, headers=headers)).json()
    assert get_ok["message"] is None

    await _settle_tasks()
