"""Abort alembic unless the DSN is local or APP_ENV is exactly production.

Fail-closed: unknown APP_ENV (typo ``produciton``, ``staging``, ``prod``) plus a
remote DSN is blocked. Localhost / 127.0.0.1 is always allowed so local alembic
keeps working. Remote DSN is allowed only when app_env == ``production``.
"""

from __future__ import annotations

from urllib.parse import urlparse

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})
_PRODUCTION_ENV = "production"


def database_url_host(database_url: str) -> str:
    """Hostname from a SQLAlchemy DSN (postgresql+asyncpg://...). Empty if missing."""
    if not database_url:
        return ""
    parsed = urlparse(database_url)
    return (parsed.hostname or "").lower()


def assert_safe_alembic_dsn(app_env: str, database_url: str) -> None:
    """Raise SystemExit when a non-production env would hit a non-local DSN.

    Message always contains ``prod DSN blocked`` so operators can grep logs.
    """
    env = (app_env or "").strip()
    host = database_url_host(database_url)
    if host in _LOCAL_HOSTS:
        return
    if env == _PRODUCTION_ENV:
        return
    raise SystemExit(
        f"prod DSN blocked: APP_ENV={app_env!r} cannot run alembic against "
        f"host {host!r} (remote DSN is allowed only when APP_ENV is "
        f"{_PRODUCTION_ENV!r})"
    )
