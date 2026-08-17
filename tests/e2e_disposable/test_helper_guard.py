"""DE-19 / DE-20 / DE-21 — prod-safety guards for the lane itself.

The repo ``.env`` ``DATABASE_URL`` points at Supabase PRODUCTION and
``apps/api/migrations/env.py`` has NO local-host guard, so an unpinned command
from this lane would run DDL against production. Defence in depth:

* the SHELL helper refuses a non-localhost DSN (DE-19) and tears down
  unconditionally (DE-20);
* the IN-PROCESS session-scoped guard refuses a direct
  ``pytest tests/e2e_disposable/`` that falls through to
  ``tests/conftest.py:24``'s ``setdefault`` — which would reach the SHARED dev DB
  on :5433 and ``DROP SCHEMA`` it (DE-21).
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.e2e_disposable.conftest import REPO_ROOT, assert_disposable_dsn

pytestmark = pytest.mark.disposable

HELPER = REPO_ROOT / "scripts" / "e2e-disposable.sh"
DOCKER = "/Applications/Docker.app/Contents/Resources/bin/docker"

_PROD_DSN = "postgresql+asyncpg://u:p@db.hylcleqxlkdblibpdhhm.supabase.co:5432/postgres"


def _running_e2e_containers() -> list[str]:
    out = subprocess.run(
        [DOCKER, "ps", "--format", "{{.Names}}"], capture_output=True, text=True
    ).stdout
    return [n for n in out.split() if n.startswith("e2e-")]


# ── DE-19 — the helper refuses a non-localhost DSN ───────────────────────────


@pytest.mark.parametrize(
    "dsn",
    [
        _PROD_DSN,
        "postgresql+asyncpg://u:p@10.0.0.5:5432/db",
        "not-a-dsn-at-all",
    ],
)
def test_de19_helper_refuses_non_local_or_unparseable_dsn(dsn):
    proc = subprocess.run(
        [str(HELPER), "guardtest", "--dsn", dsn],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=120,
    )
    assert proc.returncode != 0, f"helper accepted {dsn!r}"
    assert proc.stdout.strip() == "", (
        "a refusing helper must print NOTHING on stdout — a caller doing "
        "`eval $(e2e-disposable.sh ...)` would otherwise export a prod DSN"
    )
    assert "ABORT" in proc.stderr


def test_de19_allow_remote_is_the_deliberate_override(tmp_path):
    """The refusal is a guard, not a wall — but it takes an explicit flag.

    Asserted by absence of the refusal message; the run then proceeds to start a
    real (local) container, so it is short-circuited with a no-op command.
    """
    proc = subprocess.run(
        [str(HELPER), "guardtest", "--dsn", _PROD_DSN, "--allow-remote", "--", "true"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=300,
    )
    assert "is not localhost — refusing" not in proc.stderr


# ── DE-20 — teardown is unconditional ────────────────────────────────────────


def test_de20_teardown_after_a_failing_command():
    before = set(_running_e2e_containers())
    proc = subprocess.run(
        [str(HELPER), "teardownfail", "--", "bash", "-c", "exit 7"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=300,
    )
    assert proc.returncode == 7, "the helper must propagate the command's exit code"
    assert set(_running_e2e_containers()) == before, "containers leaked on failure"


def test_de20_teardown_after_sigint():
    """Ctrl-C mid-run must leave nothing behind (`trap ... EXIT INT TERM`)."""
    before = set(_running_e2e_containers())
    proc = subprocess.Popen(
        [str(HELPER), "teardownint"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(REPO_ROOT),
        start_new_session=True,
    )
    try:
        deadline = time.time() + 180
        started = False
        while time.time() < deadline:
            line = proc.stdout.readline()
            if line.startswith("REDIS_URL="):
                started = True
                break
            if proc.poll() is not None:
                break
        assert started, "helper never brought the stack up"
        assert set(_running_e2e_containers()) - before, "no container was started"

        os.killpg(os.getpgid(proc.pid), signal.SIGINT)
        proc.wait(timeout=120)
    finally:
        if proc.poll() is None:
            proc.kill()

    for _ in range(60):
        if set(_running_e2e_containers()) == before:
            break
        time.sleep(1)
    assert set(_running_e2e_containers()) == before, "containers leaked after SIGINT"


# ── DE-21 — in-process DSN guard ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "dsn",
    [
        "",  # unset — would fall through to conftest.py:24's setdefault
        "postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent_test",
        "postgresql+asyncpg://retarget:x@localhost:5432/retarget_agent",
        "postgresql+asyncpg://u:p@aws-1-ap-southeast-1.pooler.supabase.com:6543/postgres",
        _PROD_DSN,
        "postgresql+asyncpg://u:p@localhost/nodb",  # unparseable port
    ],
)
def test_de21_guard_refuses_shared_and_remote_targets(dsn):
    with pytest.raises(RuntimeError):
        assert_disposable_dsn(dsn)


def test_de21_guard_accepts_an_ephemeral_local_port():
    """Anti-vacuity: the guard must not simply refuse everything."""
    ok = "postgresql+asyncpg://e2e:e2e@localhost:57123/e2e"
    assert assert_disposable_dsn(ok) == ok


def test_de21_direct_pytest_against_the_shared_dev_db_hard_fails_at_setup():
    """The strong leg: a REAL pytest run with a non-conforming DSN must abort at
    session setup, BEFORE any DROP SCHEMA reaches the shared dev DB on :5433."""
    env = dict(os.environ)
    env["DATABASE_URL"] = (
        "postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent_test"
    )
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/e2e_disposable/test_migration_truth.py::test_de2_coop_indexes_exist_after_alembic_upgrade",
            "-p",
            "no:randomly",
            "-q",
            # `addopts` carries --ignore=tests/e2e_disposable, which would skip
            # the explicitly-named file and make this leg vacuous.
            "-o",
            "addopts=",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=300,
    )
    assert proc.returncode != 0
    combined = proc.stdout + proc.stderr
    assert "REFUSING disposable lane" in combined, combined[-3000:]
    assert "port 5433 is reserved" in combined
