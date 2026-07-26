"""AC8 / AC9 — the `celery_worker_enabled` gate on every `.delay()` call site.

Proves the resolved truth table for both async push surfaces (CRM router and the
shared ads push service):

    *_async_push | celery_worker_enabled | behavior
    -------------|-----------------------|-------------------------------------
    True         | False                 | inline, NEVER .delay()  (AC8)
    True         | True                  | .delay(), no inline duplicate (AC9)
    False        | True                  | inline (async is opt-in per surface)

The dangerous cell is row 1: queueing there drops the work silently because no
worker consumes the broker. Pure unit test — no DB, no Redis, no broker.
"""

import pytest

from apps.api.config import settings
from apps.api.routers import crm as crm_router
from apps.api.services import ads_push
from apps.api.tasks import ads_tasks, crm_tasks

pytestmark = pytest.mark.unit


class _InlineReached(Exception):
    """Raised by a stubbed inline dependency to prove the inline path ran."""


class _FakeTask:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def delay(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return object()


class _Scalarable:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDb:
    """Minimal AsyncSession stand-in for the two queries the push path makes."""

    def __init__(self, member_count: int) -> None:
        self._member_count = member_count

    async def execute(self, *_args, **_kwargs):
        return _Scalarable(object())  # a Segment / connection row exists

    async def scalar(self, *_args, **_kwargs):
        return self._member_count


@pytest.fixture
def crm_env(monkeypatch):
    """Wire the CRM push endpoint so only the async-vs-inline branch matters."""
    task = _FakeTask()
    monkeypatch.setattr(crm_tasks, "push_segment_to_crm", task)

    async def _owned_site(*_a, **_kw):
        return object()

    async def _get_connection(*_a, **_kw):
        return object()

    async def _reserve(*_a, **_kw):
        return True

    async def _push_segment(*_a, **_kw):
        raise _InlineReached("crm inline push ran")

    monkeypatch.setattr(crm_router, "_owned_site", _owned_site)
    monkeypatch.setattr(crm_router, "get_connection", _get_connection)
    monkeypatch.setattr(crm_router, "check_and_reserve_push", _reserve)
    monkeypatch.setattr(crm_router, "push_segment", _push_segment)
    monkeypatch.setattr(settings, "crm_async_push_threshold", 10)
    return task


async def _call_crm(member_count: int):
    body = crm_router.PushSegmentRequest(segment_id="seg_1")
    return await crm_router.push_segment_endpoint(
        site_id="site_a",
        provider="hubspot",
        body=body,
        user=object(),
        db=_FakeDb(member_count),
    )


# ── AC8 — flag OFF: inline, never .delay() ───────────────────────────────


async def test_crm_worker_disabled_runs_inline_and_never_delays(monkeypatch, crm_env):
    monkeypatch.setattr(settings, "crm_async_push", True)
    monkeypatch.setattr(settings, "celery_worker_enabled", False)

    # Over the async threshold — today this would have queued into a broker with
    # no consumer. The gate must force the inline path instead.
    with pytest.raises(_InlineReached):
        await _call_crm(member_count=500)

    assert crm_env.calls == []


async def test_crm_async_off_worker_on_still_runs_inline(monkeypatch, crm_env):
    monkeypatch.setattr(settings, "crm_async_push", False)
    monkeypatch.setattr(settings, "celery_worker_enabled", True)

    with pytest.raises(_InlineReached):
        await _call_crm(member_count=500)

    assert crm_env.calls == []


# ── AC9 — flag ON: .delay(), no inline duplicate ─────────────────────────


async def test_crm_worker_enabled_delays_and_skips_inline(monkeypatch, crm_env):
    monkeypatch.setattr(settings, "crm_async_push", True)
    monkeypatch.setattr(settings, "celery_worker_enabled", True)

    result = await _call_crm(member_count=500)

    assert result.queued is True
    assert result.pushed == 0
    assert crm_env.calls == [(("site_a", "hubspot", "seg_1"), {})]


async def test_crm_under_threshold_runs_inline_even_with_both_flags_on(
    monkeypatch, crm_env
):
    monkeypatch.setattr(settings, "crm_async_push", True)
    monkeypatch.setattr(settings, "celery_worker_enabled", True)

    with pytest.raises(_InlineReached):
        await _call_crm(member_count=1)

    assert crm_env.calls == []


# ── Same truth table for the ads push service ────────────────────────────


@pytest.fixture
def ads_env(monkeypatch):
    task = _FakeTask()
    monkeypatch.setattr(ads_tasks, "push_segment_to_ads_task", task)

    async def _get_connection(*_a, **_kw):
        return object()

    async def _segment_visitors(*_a, **_kw):
        raise _InlineReached("ads inline push ran")

    monkeypatch.setattr(ads_push, "get_connection", _get_connection)
    monkeypatch.setattr(ads_push, "_get_segment_visitors", _segment_visitors)
    monkeypatch.setattr(settings, "ads_async_push_threshold", 10)
    return task


async def _call_ads(member_count: int):
    return await ads_push.push_segment_to_ads(
        _FakeDb(member_count), "site_a", "meta", "seg_1"
    )


async def test_ads_worker_disabled_runs_inline_and_never_delays(monkeypatch, ads_env):
    monkeypatch.setattr(settings, "ads_async_push", True)
    monkeypatch.setattr(settings, "celery_worker_enabled", False)

    with pytest.raises(_InlineReached):
        await _call_ads(member_count=500)

    assert ads_env.calls == []


async def test_ads_worker_enabled_delays_and_skips_inline(monkeypatch, ads_env):
    monkeypatch.setattr(settings, "ads_async_push", True)
    monkeypatch.setattr(settings, "celery_worker_enabled", True)

    outcome = await _call_ads(member_count=500)

    assert outcome.queued is True
    assert outcome.found is True
    assert ads_env.calls == [(("site_a", "meta", "seg_1"), {})]


async def test_ads_async_off_worker_on_still_runs_inline(monkeypatch, ads_env):
    monkeypatch.setattr(settings, "ads_async_push", False)
    monkeypatch.setattr(settings, "celery_worker_enabled", True)

    with pytest.raises(_InlineReached):
        await _call_ads(member_count=500)

    assert ads_env.calls == []


# ── Default posture: the gate ships OFF ──────────────────────────────────


def test_celery_worker_enabled_defaults_off():
    from apps.api.config import Settings

    assert Settings().celery_worker_enabled is False
