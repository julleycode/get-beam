"""F10 — alembic DSN guard: remote DSN only when APP_ENV is exactly production.

Fail-closed for unknown env (typo ``produciton``, ``staging``, ``prod``).
Monkeypatch-only: never opens a real connection. Message must mention
``prod DSN blocked``. Localhost + development must still pass.
"""

import pytest

from apps.api.alembic_dsn_guard import assert_safe_alembic_dsn, database_url_host

pytestmark = pytest.mark.unit

_PROD_DSN = (
    "postgresql+asyncpg://postgres.abc:secret@aws-0-ap-southeast-1"
    ".pooler.supabase.co:5432/postgres"
)
_LOCAL_DSN = "postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent"
_LOOPBACK_DSN = "postgresql+asyncpg://retarget:retarget_dev@127.0.0.1:5433/retarget_agent"


class TestDatabaseUrlHost:
    def test_parses_asyncpg_localhost(self):
        assert database_url_host(_LOCAL_DSN) == "localhost"

    def test_parses_supabase_pooler_host(self):
        assert database_url_host(_PROD_DSN) == "aws-0-ap-southeast-1.pooler.supabase.co"

    def test_empty_url_is_empty_host(self):
        assert database_url_host("") == ""


class TestAssertSafeAlembicDsn:
    @pytest.mark.parametrize("env", ["local", "development", "test", "ci"])
    def test_nonprod_env_plus_prod_dsn_aborts(self, env):
        with pytest.raises(SystemExit, match="prod DSN blocked") as exc:
            assert_safe_alembic_dsn(env, _PROD_DSN)
        assert "prod DSN blocked" in str(exc.value)

    @pytest.mark.parametrize("env", ["local", "development", "test", "ci"])
    def test_nonprod_env_plus_localhost_is_allowed(self, env):
        assert_safe_alembic_dsn(env, _LOCAL_DSN)

    def test_development_plus_loopback_is_allowed(self):
        assert_safe_alembic_dsn("development", _LOOPBACK_DSN)

    def test_production_env_plus_prod_dsn_is_allowed(self):
        """Operators apply prod migrations with APP_ENV=production on purpose."""
        assert_safe_alembic_dsn("production", _PROD_DSN)

    @pytest.mark.parametrize("env", ["produciton", "staging", "prod"])
    def test_unknown_env_plus_prod_dsn_aborts(self, env):
        """Typos / aliases must not bypass the remote-DSN block."""
        with pytest.raises(SystemExit, match="prod DSN blocked") as exc:
            assert_safe_alembic_dsn(env, _PROD_DSN)
        assert "prod DSN blocked" in str(exc.value)

    def test_settings_monkeypatch_nonprod_prod_dsn(self, monkeypatch):
        from apps.api.config import settings

        monkeypatch.setattr(settings, "app_env", "local")
        monkeypatch.setattr(settings, "database_url", _PROD_DSN)
        with pytest.raises(SystemExit, match="prod DSN blocked"):
            assert_safe_alembic_dsn(settings.app_env, settings.database_url)

    def test_settings_monkeypatch_development_localhost(self, monkeypatch):
        from apps.api.config import settings

        monkeypatch.setattr(settings, "app_env", "development")
        monkeypatch.setattr(settings, "database_url", _LOCAL_DSN)
        assert_safe_alembic_dsn(settings.app_env, settings.database_url)
