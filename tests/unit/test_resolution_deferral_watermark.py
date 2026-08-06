"""A dead provider tier defers the visitor; a silent one still writes them off.

`unresolvable` is terminal — both sweeps select `anonymous` only — so writing it
while the providers were DOWN deletes the visitor from every future run over a
fault that was ours to wait out. These tests pin the separation.

Every test drives the real `resolve()` end to end. That is deliberate and is the
whole reason this file exists: the previous attempt at this feature shipped with
four green tests that hand-set the outage counters and called the final-state
helper directly, so none of them ever exercised the branch that decides those
counters. The bug they were written to catch — one pair of counters shared by
both tiers, so a healthy ipinfo masked three dead person-graph providers — sat
in the code untouched. Counters are an implementation detail; the contract is
what `resolve()` leaves on the visitor row.
"""
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.services.identity_providers.base import (
    ProviderNotConfiguredError,
    ProviderUnavailableError,
)
from apps.api.services.identity_resolver import (
    RESOLUTION_DEFER_BACKOFF,
    TIER_ALL_UNAVAILABLE,
    TIER_ANSWERED,
    TIER_NOT_APPLICABLE,
    IdentityResolver,
    tier_verdict,
)


def _make_visitor(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "site_id": "test-site",
        "visitor_id": f"v-{uuid.uuid4().hex[:8]}",
        "ip_address": "203.0.113.42",
        "fingerprint": None,
        "server_visitor_id": None,
        "identity_status": "anonymous",
        "country_code": None,
        "company_domain": None,
        "do_not_resolve": False,
        "user_agent": "Mozilla/5.0",
        "resolution_deferred_until": None,
        "resolution_defer_count": 0,
        "first_seen": datetime.now(timezone.utc),
        "last_seen": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _fake_redis():
    """An empty, per-test Redis.

    Never pass redis_client=None here: the resolver then builds a REAL client,
    and these tests would share one live cache keyed by visitor IP. That is not
    hypothetical — it made the IP-outage test pass through a "__none__" marker
    written by an earlier test in this same file, skipping the IP tier entirely
    and inverting the result.
    """
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.exists = AsyncMock(return_value=0)
    redis.setex = AsyncMock()
    return redis


def _make_resolver(redis_client=None):
    """A resolver with every gate BEFORE the waterfall opened.

    Only the pre-waterfall gates are stubbed (privacy, prior signals, recency,
    budget). The waterfall itself — both parallel tiers and the final-state
    branch — runs for real.
    """
    redis_client = redis_client if redis_client is not None else _fake_redis()
    db = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    resolver = IdentityResolver(db=db, redis_client=redis_client)
    resolver._is_email_opted_out = AsyncMock(return_value=False)
    resolver._check_prior_signals = AsyncMock(return_value=None)
    resolver.was_recently_attempted = AsyncMock(return_value=False)
    resolver.check_daily_budget = AsyncMock(return_value=True)
    resolver._log_resolution = AsyncMock()
    return resolver


def _settings(mock_settings, **overrides):
    """Every provider on with a key, unless a test says otherwise."""
    defaults = {
        "leadpipe_enabled": True,
        "leadpipe_api_key": "k",
        "capturify_enabled": True,
        "capturify_api_key": "k",
        "rb2b_enabled": True,
        "rb2b_api_key": "k",
        "pdl_ip_enabled": True,
        "people_data_labs_api_key": "k",
        "ipinfo_enabled": True,
        "ipinfo_token": "k",
        "company_graph_enabled": False,
    }
    defaults.update(overrides)
    for key, value in defaults.items():
        setattr(mock_settings, key, value)
    return mock_settings


async def _down(_visitor):
    raise ProviderUnavailableError("HTTP 403: Organization is expired")


async def _not_configured(_visitor):
    raise ProviderNotConfiguredError("no pixel for this domain")


async def _no_match(_visitor):
    return None


def _wire(resolver, *, leadpipe=_no_match, capturify=_no_match, rb2b=_no_match,
          pdl=_no_match, ipinfo=_no_match):
    resolver._call_leadpipe_api = leadpipe
    resolver._call_capturify_api = capturify
    resolver._call_rb2b_api = rb2b
    resolver._call_pdl_ip_enrich = pdl
    resolver._call_ipinfo_api = ipinfo


def _patched(fn):
    """Stack the two patches every waterfall test needs."""
    fn = patch(
        "apps.api.services.identity_resolver.check_ip_privacy",
        new=AsyncMock(return_value={}),
    )(fn)
    return patch("apps.api.services.identity_resolver.settings")(fn)


class TestEverySweepHonoursTheWatermark:
    """Structural guard: a watermark only one sweep respects is no watermark.

    The deferral column shipped once before with the filter added to
    `resolution_runner.py` alone. The Celery-beat sweep in `resolution_tasks.py`
    — same `anonymous` filter, larger LIMIT, live in production — kept selecting
    deferred visitors on every run, paying for the privacy check each time and
    driving the backoff to exhaustion on its own. Both files individually looked
    correct; only together did they show the hole.

    So this discovers sweeps instead of listing them: any file that narrows on
    `anonymous` AND actually awaits `resolve()` must carry the filter. A third
    one added later fails here rather than silently reopening the hole.
    """

    SWEEP_ROOT = Path(__file__).resolve().parents[2] / "apps" / "api"
    # An awaited call, not a bare ".resolve(" — the loose form also matches
    # prose like "mirrors IdentityResolver.resolve()" in a docstring.
    AWAITS_RESOLVE = re.compile(r"await\s+[\w.()]+\.resolve\(")

    def _sweeps(self) -> list[Path]:
        found = []
        for path in self.SWEEP_ROOT.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if 'identity_status == "anonymous"' not in source:
                continue
            if self.AWAITS_RESOLVE.search(source):
                found.append(path)
        return found

    def test_both_known_sweeps_are_discovered(self):
        names = {p.name for p in self._sweeps()}
        # Pins the discovery itself: a rename or refactor that hides a sweep
        # from this scan would otherwise make the test below vacuously pass.
        assert {"resolution_runner.py", "resolution_tasks.py"} <= names

    def test_every_sweep_filters_deferred_visitors(self):
        missing = [
            p.name
            for p in self._sweeps()
            if "resolution_not_deferred_filter()" not in p.read_text(encoding="utf-8")
        ]
        assert not missing, (
            f"sweep(s) select anonymous visitors without the deferral filter: "
            f"{missing} — deferred visitors will be re-resolved every run"
        )


class TestTierVerdict:
    """The rule the whole feature turns on, in isolation."""

    def test_no_attempts_is_not_applicable(self):
        assert tier_verdict(0, 0) == TIER_NOT_APPLICABLE

    def test_every_attempt_unavailable(self):
        assert tier_verdict(3, 3) == TIER_ALL_UNAVAILABLE

    def test_one_answer_is_enough_to_answer(self):
        assert tier_verdict(3, 2) == TIER_ANSWERED

    def test_unconfigured_providers_leave_the_denominator(self):
        # Two of three never looked: the one that DID look and failed still
        # means the tier produced no verdict, so the tier counts as down.
        assert tier_verdict(1, 1) == TIER_ALL_UNAVAILABLE


class TestPersonGraphOutage:
    """The case that motivated the feature — and that the last attempt missed."""

    @pytest.mark.asyncio
    @_patched
    async def test_dead_graphs_plus_healthy_ipinfo_defers(
        self, mock_settings, *_
    ):
        # The exact shape of the bug in the reverted attempt: three person-graph
        # providers share one expired account, ipinfo answers normally and finds
        # nobody. With merged counters "somebody answered" wins and the visitor
        # is written off. Per tier, the dead tier is visible.
        _settings(mock_settings, pdl_ip_enabled=False)
        resolver = _make_resolver()
        _wire(resolver, leadpipe=_down, capturify=_down, rb2b=_down)
        visitor = _make_visitor()

        assert await resolver.resolve(visitor) is None

        assert visitor.identity_status == "anonymous"
        assert visitor.resolution_defer_count == 1
        assert visitor.resolution_deferred_until is not None

    @pytest.mark.asyncio
    @_patched
    async def test_ip_tier_outage_alone_also_defers(self, mock_settings, *_):
        # Mirror image: person-graph answers no-match, the IP tier is down.
        # Both tiers are checked independently; neither can veto the other.
        _settings(mock_settings)
        resolver = _make_resolver()
        _wire(resolver, pdl=_down, ipinfo=_down)
        visitor = _make_visitor()

        await resolver.resolve(visitor)

        assert visitor.identity_status == "anonymous"
        assert visitor.resolution_defer_count == 1


class TestNoDeferralWhenProvidersSpoke:
    """Deferral must stay rare: only a tier that could NOT answer earns it."""

    @pytest.mark.asyncio
    @_patched
    async def test_plain_no_match_still_terminal(self, mock_settings, *_):
        _settings(mock_settings)
        resolver = _make_resolver()
        _wire(resolver)  # everybody answers, nobody matches
        visitor = _make_visitor()

        await resolver.resolve(visitor)

        assert visitor.identity_status == "unresolvable"
        assert visitor.resolution_defer_count == 0
        assert visitor.resolution_deferred_until is None

    @pytest.mark.asyncio
    @_patched
    async def test_unconfigured_provider_is_not_an_outage(
        self, mock_settings, *_
    ):
        # A site with no Leadpipe pixel raises ProviderNotConfiguredError on
        # every resolve. Counting that as "unavailable" would defer every
        # visitor of every site that has not switched Leadpipe on — four wasted
        # sweep rounds each, forever, over a config gap rather than an outage.
        _settings(mock_settings, capturify_enabled=False)
        resolver = _make_resolver()
        _wire(resolver, leadpipe=_not_configured)  # rb2b answers, ipinfo/pdl answer
        visitor = _make_visitor()

        await resolver.resolve(visitor)

        assert visitor.identity_status == "unresolvable"
        assert visitor.resolution_defer_count == 0

    @pytest.mark.asyncio
    @_patched
    async def test_no_providers_configured_stays_terminal(
        self, mock_settings, *_
    ):
        # Nothing enabled anywhere: every tier is not_applicable. This must stay
        # terminal, or the sweep would re-select these visitors forever.
        _settings(
            mock_settings,
            leadpipe_enabled=False,
            capturify_enabled=False,
            rb2b_enabled=False,
            pdl_ip_enabled=False,
            ipinfo_enabled=False,
        )
        resolver = _make_resolver()
        _wire(resolver)
        visitor = _make_visitor()

        await resolver.resolve(visitor)

        assert visitor.identity_status == "unresolvable"
        assert visitor.resolution_deferred_until is None


class TestBackoff:
    """Waiting is bounded: an outage that outlasts the schedule is a dead key."""

    @pytest.mark.asyncio
    @_patched
    async def test_each_step_uses_the_next_interval(self, mock_settings, *_):
        _settings(mock_settings, pdl_ip_enabled=False, ipinfo_enabled=False)
        resolver = _make_resolver()
        _wire(resolver, leadpipe=_down, capturify=_down, rb2b=_down)
        visitor = _make_visitor()

        for step, expected in enumerate(RESOLUTION_DEFER_BACKOFF, start=1):
            before = datetime.now(timezone.utc).replace(tzinfo=None)
            await resolver.resolve(visitor)

            assert visitor.identity_status == "anonymous"
            assert visitor.resolution_defer_count == step
            waited = visitor.resolution_deferred_until - before
            # Bounded both sides: catches an off-by-one into the wrong step.
            assert expected <= waited <= expected + timedelta(seconds=30)

    @pytest.mark.asyncio
    @_patched
    async def test_past_the_last_step_writes_off_and_resets(
        self, mock_settings, *_
    ):
        _settings(mock_settings, pdl_ip_enabled=False, ipinfo_enabled=False)
        resolver = _make_resolver()
        _wire(resolver, leadpipe=_down, capturify=_down, rb2b=_down)
        visitor = _make_visitor(
            resolution_defer_count=len(RESOLUTION_DEFER_BACKOFF)
        )

        await resolver.resolve(visitor)

        assert visitor.identity_status == "unresolvable"
        # Reset, so a later revival (IP change) or manual Retry starts from a
        # clean schedule instead of inheriting a spent one and dying instantly.
        assert visitor.resolution_defer_count == 0
        assert visitor.resolution_deferred_until is None


class TestManualRetryIgnoresTheWatermark:
    """"Retry" must mean now, even mid-outage."""

    @pytest.mark.asyncio
    @_patched
    async def test_deferred_visitor_still_runs_the_waterfall(
        self, mock_settings, *_
    ):
        # The watermark lives in the sweep QUERIES, never inside resolve(), so
        # the per-visitor Retry button reaches the providers regardless. Pinned
        # because moving the check into resolve() would look equivalent and
        # would silently disable Retry for exactly the visitors most likely to
        # have it pressed.
        _settings(mock_settings, pdl_ip_enabled=False, ipinfo_enabled=False)
        resolver = _make_resolver()
        called = []

        async def _seen(_visitor):
            called.append("leadpipe")
            return None

        _wire(resolver, leadpipe=_seen)
        visitor = _make_visitor(
            resolution_deferred_until=datetime.now(timezone.utc).replace(tzinfo=None)
            + timedelta(hours=6),
            resolution_defer_count=2,
        )

        await resolver.resolve(visitor, force_retry=True)

        assert called == ["leadpipe"]


class TestNegativeCache:
    """An empty answer from a dead tier says nothing about the IP."""

    @pytest.mark.asyncio
    @_patched
    async def test_ip_outage_writes_no_none_marker(self, mock_settings, *_):
        # Caching "__none__" for 24h here would keep skipping the IP→company
        # step long after the providers recovered — the deferred retry would
        # come back, find the cache, and learn nothing.
        _settings(mock_settings)
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.exists = AsyncMock(return_value=0)
        redis.setex = AsyncMock()
        resolver = _make_resolver(redis_client=redis)
        _wire(resolver, pdl=_down, ipinfo=_down)

        await resolver.resolve(_make_visitor())

        redis.setex.assert_not_awaited()

    @pytest.mark.asyncio
    @_patched
    async def test_genuine_no_match_still_caches(self, mock_settings, *_):
        # The negative cache is a real cost control — it must survive for the
        # case it was built for: providers answered, this IP has no company.
        _settings(mock_settings)
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.exists = AsyncMock(return_value=0)
        redis.setex = AsyncMock()
        resolver = _make_resolver(redis_client=redis)
        _wire(resolver)

        await resolver.resolve(_make_visitor())

        redis.setex.assert_awaited_once()
        assert redis.setex.await_args.args[2] == "__none__"
