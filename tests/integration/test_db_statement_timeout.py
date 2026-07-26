"""AC11 — server-side ``statement_timeout`` (capacity-hardening Phase 4a / W4).

Docker-gated: needs a real Postgres (``docker compose -f infra/docker-compose.yml
up -d postgres``).

The point of 4a is that the timeout is applied SERVER-SIDE via asyncpg
``server_settings``, so Postgres kills the backend itself. A client-side cancel
would return control to the app while the backend kept burning the connection —
which is the exact failure (one slow query holding 1 of 5 pooled connections
indefinitely) the item exists to prevent.

Both directions are asserted: a non-zero value kills an over-budget query, and
``db_statement_timeout_ms=0`` disables the timeout entirely (today's behavior).
These use their own short-lived engines rather than the module-level ``engine``,
so the app's real pool is never reconfigured mid-run.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from apps.api.config import settings
from apps.api.models.database import build_connect_args

pytestmark = pytest.mark.integration


def _engine(timeout_ms: int):
    return create_async_engine(
        settings.database_url,
        pool_size=1,
        max_overflow=0,
        connect_args=build_connect_args(settings.database_url, timeout_ms),
    )


class TestStatementTimeout:
    async def test_a_query_over_the_budget_is_killed_server_side(self):
        engine = _engine(500)
        try:
            with pytest.raises(Exception) as exc:
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT pg_sleep(5)"))
            # asyncpg raises QueryCanceledError; SQLAlchemy wraps it. Assert on
            # the message rather than the driver class so this does not break on
            # a driver upgrade.
            assert "canceling statement" in str(exc.value).lower()
        finally:
            await engine.dispose()

    async def test_a_query_under_the_budget_still_succeeds(self):
        engine = _engine(5000)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT pg_sleep(0.1)"))
                assert result is not None
        finally:
            await engine.dispose()

    async def test_zero_disables_the_timeout(self):
        """0 = today's exact behavior: the key is never sent at all."""
        assert "server_settings" not in build_connect_args(settings.database_url, 0)
        engine = _engine(0)
        try:
            async with engine.connect() as conn:
                row = await conn.execute(text("SHOW statement_timeout"))
                # Server default (0 / '0' on a stock container) — not our value.
                assert row.scalar() in ("0", "0ms")
                await conn.execute(text("SELECT pg_sleep(1.5)"))
        finally:
            await engine.dispose()


class TestConnectArgsInvariants:
    """E5 — both asyncpg cache keys survive the ``server_settings`` addition."""

    SUPABASE_URL = "postgresql+asyncpg://u:p@db.abc.supabase.co:5432/postgres"
    SUPABASE_TXN_URL = "postgresql+asyncpg://u:p@db.abc.supabase.co:6543/postgres"

    @pytest.mark.parametrize("url", [SUPABASE_URL, SUPABASE_TXN_URL])
    @pytest.mark.parametrize("timeout_ms", [0, 30_000])
    def test_both_cache_keys_are_preserved_for_both_pooler_modes(
        self, url: str, timeout_ms: int
    ):
        args = build_connect_args(url, timeout_ms)
        assert args["prepared_statement_cache_size"] == 0
        assert args["statement_cache_size"] == 0

    def test_server_settings_is_added_only_when_the_timeout_is_set(self):
        assert build_connect_args(self.SUPABASE_URL, 0).get("server_settings") is None
        assert build_connect_args(self.SUPABASE_URL, 30_000)["server_settings"] == {
            "statement_timeout": "30000"
        }

    def test_a_non_supabase_url_gets_no_cache_keys(self):
        args = build_connect_args("postgresql+asyncpg://u:p@localhost:5432/x", 0)
        assert args == {}
