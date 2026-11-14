"""Fail-closed guard: stop online alembic runs against a remote database by accident.

Repo-root ``.env`` points ``DATABASE_URL`` at PRODUCTION Supabase, so a bare
``alembic upgrade`` on a dev machine used to migrate prod. This guard runs in
``apps/api/migrations/env.py`` before any ONLINE connection is opened (offline
``--sql`` mode opens no connection and is not guarded).

Allowed:
  1. DSN host is local: ``localhost`` / ``127.0.0.1`` / ``::1`` /
     ``host.docker.internal`` / a dot-less container name (``postgres``, ``db``).
  2. ``RAILWAY_ENVIRONMENT`` is set — Railway injects it; the Dockerfile runs
     ``alembic upgrade head`` at boot and that MUST keep working.
  3. ``ALEMBIC_ALLOW_REMOTE=1`` — explicit operator opt-in.
Anything else (including an unparseable / host-less DSN) raises.

Deliberately NOT keyed on ``APP_ENV``: a dev ``.env`` can say anything, and a
typo there must not unlock prod.
"""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlparse

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "host.docker.internal"})


class RemoteDsnBlocked(RuntimeError):
    """Raised when alembic would run against a non-local DSN without opt-in."""


def database_url_host(database_url: str) -> str:
    """Lower-cased hostname of a SQLAlchemy DSN, or "" when absent/unparseable."""
    if not database_url:
        return ""
    try:
        return (urlparse(database_url).hostname or "").lower()
    except ValueError:
        return ""


def is_local_host(host: str) -> bool:
    if not host:
        return False
    return host in _LOCAL_HOSTS or "." not in host and ":" not in host


def alembic_dsn_allowed(database_url: str, environ: Mapping[str, str]) -> tuple[bool, str]:
    """Pure decision: (allowed, reason). Never raises."""
    host = database_url_host(database_url)
    if is_local_host(host):
        return True, "local-host"
    if environ.get("RAILWAY_ENVIRONMENT"):
        return True, "railway"
    if environ.get("ALEMBIC_ALLOW_REMOTE") == "1":
        return True, "explicit-opt-in"
    return False, host or "<no host>"


def assert_safe_alembic_dsn(database_url: str, environ: Mapping[str, str]) -> None:
    allowed, reason = alembic_dsn_allowed(database_url, environ)
    if allowed:
        return
    raise RemoteDsnBlocked(
        f"remote DSN blocked: refusing to run alembic against host {reason!r}. "
        "Point DATABASE_URL at a local database (e.g. localhost:5433), or set "
        "ALEMBIC_ALLOW_REMOTE=1 if you really mean to migrate this database."
    )
