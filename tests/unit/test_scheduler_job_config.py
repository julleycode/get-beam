"""AST gates over ``apps/api/jobs/scheduler.py``.

Covers **AC-V6 / E18** (the ``aggregation_sweep`` boot offset, Phase 3) and
**AC13 / E20** (``jitter`` + ``misfire_grace_time`` on every interval
``add_job``, Phase 4c).

Per E20 the authoritative arithmetic is **12 add_job calls total, 11 interval
(all asserted), 1 CronTrigger excluded**. Every count below is DERIVED by walking
the AST, never hardcoded to a line number — line numbers shift the moment a job
is inserted, which is exactly what Phase 3 did to Phase 4c's arithmetic.
"""

import ast
import pathlib

import pytest

pytestmark = pytest.mark.unit

SCHEDULER_PATH = (
    pathlib.Path(__file__).resolve().parents[2] / "apps" / "api" / "jobs" / "scheduler.py"
)


def _add_job_calls() -> list[ast.Call]:
    tree = ast.parse(SCHEDULER_PATH.read_text())
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_job"
    ]


def _kwargs(call: ast.Call) -> dict[str, ast.expr]:
    return {kw.arg: kw.value for kw in call.keywords if kw.arg}


def _job(job_id: str) -> ast.Call:
    for call in _add_job_calls():
        kw = _kwargs(call)
        node = kw.get("id")
        if isinstance(node, ast.Constant) and node.value == job_id:
            return call
    raise AssertionError(f"no add_job call registers id={job_id!r}")


def _is_interval(call: ast.Call) -> bool:
    return any(
        isinstance(arg, ast.Constant) and arg.value == "interval" for arg in call.args
    )


class TestAggregationSweepRegistration:
    def test_the_sweep_job_is_registered(self):
        _job("aggregation_sweep")  # raises if absent

    def test_it_is_an_interval_trigger_on_the_new_setting(self):
        call = _job("aggregation_sweep")
        assert _is_interval(call)
        minutes = _kwargs(call)["minutes"]
        assert isinstance(minutes, ast.Attribute)
        assert minutes.attr == "aggregation_sweep_interval_minutes"

    def test_it_targets_the_sweep_job_function(self):
        call = _job("aggregation_sweep")
        assert isinstance(call.args[0], ast.Name)
        assert call.args[0].id == "_aggregation_sweep_job"

    def test_ac_v6_it_carries_an_explicit_next_run_time_boot_offset(self):
        """A 60-min interval job on a service that redeploys hourly never fires
        without one — the documented resolution_sweep failure at scheduler.py."""
        call = _job("aggregation_sweep")
        assert "next_run_time" in _kwargs(call), (
            "aggregation_sweep must set next_run_time (E18); APScheduler's first "
            "interval fire is at +interval and the API process restarts on deploy"
        )

    def test_the_boot_offset_is_larger_than_the_existing_offsets(self):
        """E18: the sweep is the heaviest job — keep it off the boot burst."""
        offsets = []
        for call in _add_job_calls():
            nrt = _kwargs(call).get("next_run_time")
            if nrt is None:
                continue
            for node in ast.walk(nrt):
                if (
                    isinstance(node, ast.Call)
                    and getattr(node.func, "id", "") == "timedelta"
                ):
                    for kw in node.keywords:
                        if kw.arg == "seconds" and isinstance(kw.value, ast.Constant):
                            offsets.append((_kwargs(call)["id"].value, kw.value.value))

        by_id = dict(offsets)
        assert "aggregation_sweep" in by_id
        others = [v for k, v in by_id.items() if k != "aggregation_sweep"]
        assert others, "expected sibling jobs with boot offsets"
        assert by_id["aggregation_sweep"] > max(others)


class TestSchedulerInventory:
    def test_every_add_job_declares_an_explicit_id(self):
        for call in _add_job_calls():
            assert "id" in _kwargs(call)

    def test_cron_jobs_are_distinguishable_from_interval_jobs(self):
        """Phase 4c excludes the CronTrigger call from its jitter assertion."""
        calls = _add_job_calls()
        interval = [c for c in calls if _is_interval(c)]
        cron = [c for c in calls if not _is_interval(c)]
        assert len(interval) + len(cron) == len(calls)
        # Every job is either interval or CronTrigger — nothing else. The cron
        # set is the two digest emails (weekly outcomes + daily activity); a new
        # entry here means a new fixed-time job that Phase 4c's jitter assertion
        # must keep excluding.
        assert {_kwargs(c)["id"].value for c in cron} == {
            "outcome_digest",
            "daily_digest",
        }


class TestAC13IntervalJobHardening:
    """AC13 / E20 — Phase 4c.

    APScheduler's default ``misfire_grace_time`` is 1 second, so a late job is
    silently skipped; and interval triggers align to BOOT time, so every
    container in a deploy fires the same job simultaneously without ``jitter``.
    Both must therefore be EXPLICIT on every interval job.
    """

    def test_every_interval_job_sets_jitter(self):
        missing = [
            _kwargs(c)["id"].value
            for c in _add_job_calls()
            if _is_interval(c) and "jitter" not in _kwargs(c)
        ]
        assert not missing, f"interval jobs missing jitter: {missing}"

    def test_every_interval_job_sets_misfire_grace_time(self):
        missing = [
            _kwargs(c)["id"].value
            for c in _add_job_calls()
            if _is_interval(c) and "misfire_grace_time" not in _kwargs(c)
        ]
        assert not missing, f"interval jobs missing misfire_grace_time: {missing}"

    def test_the_values_are_positive_literals(self):
        for call in _add_job_calls():
            if not _is_interval(call):
                continue
            kw = _kwargs(call)
            job_id = kw["id"].value
            for name in ("jitter", "misfire_grace_time"):
                node = kw[name]
                assert isinstance(node, ast.Constant), (
                    f"{job_id}.{name} must be an explicit literal, not {ast.dump(node)}"
                )
                assert isinstance(node.value, int) and node.value > 0, (
                    f"{job_id}.{name} must be a positive int (got {node.value!r}); "
                    "0 would restore the silent-skip / thundering-herd behavior"
                )

    def test_the_cron_jobs_are_excluded_from_the_jitter_requirement(self):
        """jitter semantics differ for cron — E20 excludes every CronTrigger.

        A fixed send hour is the whole point of these jobs, and their per-site
        advisory lock (not jitter) is what keeps replicas from double-sending.
        """
        cron = [c for c in _add_job_calls() if not _is_interval(c)]
        assert cron, "expected at least one CronTrigger job"
        assert [c for c in cron if "jitter" in _kwargs(c)] == []

    def test_the_asserted_set_is_derived_not_hardcoded(self):
        """E20 arithmetic: 16 total / 14 interval / 2 cron — all AST-derived.

        Was 15/13/2; +1 interval job for agent_ip_range_refresh (re-fetches the
        published per-agent IP ranges; stale ranges make real agents read as
        forged). Before that 14/12/2 → +1 interval job for
        outlier_traffic_damping_sweep (outlier/internal-traffic damping,
        27-07-26). Before that 13/12/1 → +1 cron job for daily_digest. Before
        that 12/11/1 → +1 interval job for cadence_bot_flag_sweep. Updated per
        this gate's own instruction to re-derive the arithmetic when a job is
        added — never to relax the assertion.
        """
        calls = _add_job_calls()
        interval = [c for c in calls if _is_interval(c)]
        assert len(calls) == 16, f"expected 16 add_job calls, found {len(calls)}"
        assert len(interval) == 14, (
            f"expected 14 interval calls, found {len(interval)}; if a job was "
            "added or removed, update E20's arithmetic — do not relax this gate"
        )
