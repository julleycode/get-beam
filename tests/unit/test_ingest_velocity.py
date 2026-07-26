"""Unit tests for write-time ingest velocity detection (AC-6, AC-10).

Pure logic + a fake in-memory Redis. Proves the two-condition signal shape, the
explicit TTL on every key, fail-open behaviour, the OFF-by-default gate, and
(AC-10) that this module adds no external service call.
"""

import pytest

from apps.api.services import ingest_velocity
from apps.api.services.ingest_velocity import check_velocity, evaluate_velocity

pytestmark = pytest.mark.unit


class _FakeRedis:
    """Minimal async Redis stand-in recording every EXPIRE call."""

    def __init__(self, fail=False):
        self.sets: dict[str, set] = {}
        self.expires: dict[str, int] = {}
        self.fail = fail

    async def sadd(self, key, member):
        if self.fail:
            raise ConnectionError("redis down")
        self.sets.setdefault(key, set()).add(member)

    async def expire(self, key, seconds):
        if self.fail:
            raise ConnectionError("redis down")
        self.expires[key] = seconds

    async def scard(self, key):
        if self.fail:
            raise ConnectionError("redis down")
        return len(self.sets.get(key, ()))


@pytest.fixture
def velocity_on():
    """Enable velocity detection with small, deterministic thresholds."""
    from apps.api.config import settings

    prev = (
        settings.ingest_velocity_enabled,
        settings.ingest_velocity_visitor_threshold,
        settings.ingest_velocity_min_fingerprint_diversity,
        settings.ingest_velocity_window_seconds,
    )
    settings.ingest_velocity_enabled = True
    settings.ingest_velocity_visitor_threshold = 10
    settings.ingest_velocity_min_fingerprint_diversity = 0.3
    settings.ingest_velocity_window_seconds = 60
    yield settings
    (
        settings.ingest_velocity_enabled,
        settings.ingest_velocity_visitor_threshold,
        settings.ingest_velocity_min_fingerprint_diversity,
        settings.ingest_velocity_window_seconds,
    ) = prev


# ─────────────────────────── pure decision function ───────────────────────────


def test_low_visitor_count_never_flags():
    """Volume is a PRECONDITION — low diversity alone must not flag."""
    assert evaluate_velocity(5, 1, 10, 0.3) is False


def test_high_volume_high_diversity_not_flagged():
    """AC-5/AC-6: an organic spike has many visitors AND many fingerprints."""
    assert evaluate_velocity(100, 95, 10, 0.3) is False


def test_high_volume_low_diversity_flagged():
    """AC-6: many identities sharing few fingerprints is the flood signature."""
    assert evaluate_velocity(100, 5, 10, 0.3) is True


def test_diversity_exactly_at_threshold_not_flagged():
    """Boundary: the comparison is strict `<`, so == threshold is clean."""
    assert evaluate_velocity(100, 30, 10, 0.3) is False


def test_zero_visitors_never_flags():
    assert evaluate_velocity(0, 0, 0, 0.3) is False


# ───────────────────────────── redis-backed check ─────────────────────────────


@pytest.mark.asyncio
async def test_disabled_by_default_is_noop():
    """Flag defaults OFF: no key is written and nothing is ever flagged."""
    from apps.api.config import settings

    assert settings.ingest_velocity_enabled is False
    redis = _FakeRedis()
    assert await check_velocity(redis, "site1", "v1", "fp2_abc") is False
    assert redis.sets == {}


@pytest.mark.asyncio
async def test_every_key_gets_an_explicit_ttl(velocity_on):
    """Non-negotiable: unbounded key growth is a self-inflicted DoS."""
    redis = _FakeRedis()
    await check_velocity(redis, "site1", "v1", "fp2_abc")

    assert set(redis.expires) == {
        "ingest_velocity:visitors:site1",
        "ingest_velocity:fingerprints:site1",
    }
    assert all(ttl == 60 for ttl in redis.expires.values())


@pytest.mark.asyncio
async def test_ttl_refreshed_on_every_write(velocity_on):
    redis = _FakeRedis()
    await check_velocity(redis, "site1", "v1", "fp2_a")
    redis.expires.clear()
    await check_velocity(redis, "site1", "v2", "fp2_b")
    assert len(redis.expires) == 2


@pytest.mark.asyncio
async def test_flood_shape_flags(velocity_on):
    """Many distinct visitors sharing 2 fingerprints → flagged."""
    redis = _FakeRedis()
    flagged = False
    for i in range(30):
        flagged = await check_velocity(redis, "s", f"v{i}", f"fp2_{i % 2}")
    assert flagged is True


@pytest.mark.asyncio
async def test_organic_shape_does_not_flag(velocity_on):
    """Many distinct visitors each with their own fingerprint → clean."""
    redis = _FakeRedis()
    flagged = False
    for i in range(30):
        flagged = await check_velocity(redis, "s", f"v{i}", f"fp2_{i}")
    assert flagged is False


@pytest.mark.asyncio
async def test_missing_fingerprint_counted_as_own_bucket(velocity_on):
    """Omitting the fingerprint must not let an attacker suppress the signal.

    A dropped-from-denominator design would let a flood with no _fp at all evade
    detection; instead the missing value occupies one shared diversity bucket, so
    an all-missing flood still reads as low diversity.
    """
    redis = _FakeRedis()
    flagged = False
    for i in range(30):
        flagged = await check_velocity(redis, "s", f"v{i}", None)
    assert flagged is True
    assert redis.sets["ingest_velocity:fingerprints:s"] == {"__missing__"}


@pytest.mark.asyncio
async def test_fails_open_on_redis_error(velocity_on):
    """A Redis blip must never flag (and never raise into the ingest path)."""
    assert await check_velocity(_FakeRedis(fail=True), "s", "v1", "fp2_a") is False


@pytest.mark.asyncio
async def test_none_redis_is_noop(velocity_on):
    assert await check_velocity(None, "s", "v1", "fp2_a") is False


@pytest.mark.asyncio
async def test_counters_are_site_scoped(velocity_on):
    """Constraint: every new counter is scoped to a single site."""
    redis = _FakeRedis()
    await check_velocity(redis, "siteA", "v1", "fp2_a")
    await check_velocity(redis, "siteB", "v1", "fp2_a")
    assert "ingest_velocity:visitors:siteA" in redis.sets
    assert "ingest_velocity:visitors:siteB" in redis.sets


def test_ac10_no_external_service_calls():
    """AC-10: this module introduces zero new paid/external provider calls."""
    src = open(ingest_velocity.__file__).read()
    for forbidden in ("httpx", "requests", "aiohttp", "urllib.request"):
        assert forbidden not in src, f"unexpected external-call import: {forbidden}"
