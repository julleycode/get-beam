"""Unit gates over the ``--apply`` local-host guard in scripts/refresh_ip_org.py.

Pure string predicate — no network, no database. The guard exists because
``--apply`` performs ``DROP TABLE ip_org_prefixes``, and this repo's ``.env``
points ``DATABASE_URL`` at the managed production database: without the guard, a
plain ``--apply`` from a dev shell rebuilds a production table silently.

``scripts/`` is not an importable package, so the module is loaded by path.
"""

import importlib.util
import pathlib

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = (
    pathlib.Path(__file__).resolve().parents[2] / "scripts" / "refresh_ip_org.py"
)
_spec = importlib.util.spec_from_file_location("_refresh_ip_org", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

is_local_db_url = _mod.is_local_db_url


class TestIsLocalDbUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "postgresql+asyncpg://u:p@localhost:5433/retarget_agent",
            "postgresql+asyncpg://u:p@127.0.0.1:5432/db",
            "postgresql+asyncpg://u:p@[::1]:5432/db",
            "postgresql+asyncpg://u:p@host.docker.internal:5432/db",
            "postgresql+asyncpg://u:p@LOCALHOST:5433/db",  # case-insensitive
        ],
    )
    def test_local_hosts_are_allowed(self, url):
        assert is_local_db_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            # The exact DSN this repo's .env resolves to — the reason the guard exists.
            "postgresql+asyncpg://u:p@aws-1-ap-southeast-1.pooler.supabase.com:5432/postgres",
            "postgresql+asyncpg://u:p@db.example.com:5432/db",
            "postgresql+asyncpg://u:p@10.0.0.5:5432/db",  # private LAN is still remote
            "postgresql+asyncpg://u:p@localhost.evil.com:5432/db",  # suffix trick
            "postgresql+asyncpg://u:p@notlocalhost:5432/db",
        ],
    )
    def test_remote_hosts_are_refused(self, url):
        assert is_local_db_url(url) is False

    @pytest.mark.parametrize("url", ["", "not-a-url", "postgresql:///db", "://"])
    def test_it_fails_closed_on_an_unparseable_or_hostless_dsn(self, url):
        """"Cannot tell where this points" must never mean "safe to drop a table"."""
        assert is_local_db_url(url) is False

    def test_the_allowlist_is_exactly_the_four_documented_hosts(self):
        assert _mod.LOCAL_HOSTS == frozenset(
            {"localhost", "127.0.0.1", "::1", "host.docker.internal"}
        )
