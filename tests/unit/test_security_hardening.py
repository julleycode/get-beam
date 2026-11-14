"""Unit tests for fix/live-security-hardening.

Covers: CF-Connecting-IP peer check (off/shadow/enforce), alembic remote-DSN
guard, validate_production PII-key checks, engagement attribution hardening.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet
from starlette.requests import Request

from apps.api.alembic_dsn_guard import (
    RemoteDsnBlocked,
    alembic_dsn_allowed,
    assert_safe_alembic_dsn,
)
from apps.api.config import Settings, settings
from apps.api.services import ip_resolution
from apps.api.services.ip_resolution import (
    cf_header_trusted,
    is_cloudflare_ip,
    resolve_client_ip,
)

CF_EDGE = "172.70.1.2"  # inside 172.64.0.0/13
CF_EDGE_V6 = "2606:4700::1"
ATTACKER = "203.0.113.9"
REAL_CLIENT = "198.51.100.7"
RAILWAY_PROXY = "100.64.0.2"


def _req(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request(
        {"type": "http", "headers": raw, "client": (RAILWAY_PROXY, 1234), "method": "POST", "path": "/"}
    )


GENUINE = {"cf-connecting-ip": REAL_CLIENT, "x-forwarded-for": f"{REAL_CLIENT}, {CF_EDGE}"}
# Direct-to-origin forgery: the attacker also forges a CF-looking XFF prefix,
# but Railway's edge appends the real peer last.
FORGED = {"cf-connecting-ip": "1.2.3.4", "x-forwarded-for": f"{CF_EDGE}, {ATTACKER}"}
FORGED_NO_XFF = {"cf-connecting-ip": "1.2.3.4"}


# ── CF peer check ────────────────────────────────────────────────────────────


def test_cloudflare_range_membership():
    assert is_cloudflare_ip(CF_EDGE)
    assert is_cloudflare_ip(CF_EDGE_V6)
    assert not is_cloudflare_ip(ATTACKER)
    assert not is_cloudflare_ip("")
    assert not is_cloudflare_ip("not-an-ip")


@pytest.fixture
def cf_on(monkeypatch):
    monkeypatch.setattr(settings, "ingest_trust_cf_connecting_ip", True)

    def _mode(mode: str):
        monkeypatch.setattr(settings, "ingest_cf_peer_check_mode", mode)

    return _mode


def test_off_mode_trusts_forged_header(cf_on):
    cf_on("off")
    assert resolve_client_ip(_req(FORGED), trusted_proxy_hops=0) == "1.2.3.4"


@pytest.mark.parametrize("headers", [FORGED, FORGED_NO_XFF])
def test_shadow_mode_keeps_behavior_and_logs(cf_on, monkeypatch, headers):
    cf_on("shadow")
    log = MagicMock()
    monkeypatch.setattr(ip_resolution, "logger", log)
    assert resolve_client_ip(_req(headers), trusted_proxy_hops=0) == "1.2.3.4"
    log.info.assert_called_once()
    event, kwargs = log.info.call_args.args[0], log.info.call_args.kwargs
    assert event == "cf_peer_check_mismatch"
    # PII: never the full address.
    assert ATTACKER not in str(kwargs)
    if "x-forwarded-for" in headers:
        assert kwargs["peer_prefix"] == "203.0.113.0/24"


def test_shadow_mode_genuine_is_silent(cf_on, monkeypatch):
    cf_on("shadow")
    log = MagicMock()
    monkeypatch.setattr(ip_resolution, "logger", log)
    assert resolve_client_ip(_req(GENUINE), trusted_proxy_hops=0) == REAL_CLIENT
    log.info.assert_not_called()


@pytest.mark.parametrize("headers", [FORGED, FORGED_NO_XFF])
def test_enforce_rejects_forged_and_falls_back(cf_on, headers):
    cf_on("enforce")
    assert resolve_client_ip(_req(headers), trusted_proxy_hops=0) == RAILWAY_PROXY
    # Fallback honours trusted_proxy_hops path.
    if "x-forwarded-for" in headers:
        assert resolve_client_ip(_req(headers), trusted_proxy_hops=1) == ATTACKER


def test_enforce_accepts_genuine_v4_and_v6(cf_on):
    cf_on("enforce")
    assert resolve_client_ip(_req(GENUINE), trusted_proxy_hops=0) == REAL_CLIENT
    v6 = {"cf-connecting-ip": REAL_CLIENT, "x-forwarded-for": CF_EDGE_V6}
    assert resolve_client_ip(_req(v6), trusted_proxy_hops=0) == REAL_CLIENT


def test_unknown_mode_behaves_as_shadow():
    assert cf_header_trusted(_req(FORGED), "bogus") is True


def test_default_mode_is_shadow():
    assert Settings().ingest_cf_peer_check_mode == "shadow"


# ── alembic DSN guard ────────────────────────────────────────────────────────

PROD = "postgresql+asyncpg://u:p@aws-1-ap-southeast-1.pooler.supabase.com:6543/postgres"


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql+asyncpg://retarget:retarget_dev@localhost:5433/retarget_agent",
        "postgresql+asyncpg://localhost/test",
        "postgresql+asyncpg://u:p@127.0.0.1:55431/db",
        "postgresql+asyncpg://u:p@[::1]:5432/db",
        "postgresql+asyncpg://u:p@host.docker.internal:5432/db",
        "postgresql+asyncpg://u:p@postgres:5432/db",
    ],
)
def test_local_dsn_allowed(dsn):
    assert alembic_dsn_allowed(dsn, {})[0]
    assert_safe_alembic_dsn(dsn, {})


def test_remote_dsn_blocked_names_host():
    with pytest.raises(RemoteDsnBlocked, match="pooler.supabase.com"):
        assert_safe_alembic_dsn(PROD, {"APP_ENV": "production"})  # APP_ENV ignored


def test_remote_allowed_on_railway_or_opt_in():
    assert alembic_dsn_allowed(PROD, {"RAILWAY_ENVIRONMENT": "production"}) == (True, "railway")
    assert alembic_dsn_allowed(PROD, {"ALEMBIC_ALLOW_REMOTE": "1"})[0]
    assert not alembic_dsn_allowed(PROD, {"ALEMBIC_ALLOW_REMOTE": "true"})[0]
    assert not alembic_dsn_allowed(PROD, {"RAILWAY_ENVIRONMENT": ""})[0]


def test_empty_dsn_blocked():
    assert not alembic_dsn_allowed("", {})[0]


# ── validate_production PII keys ─────────────────────────────────────────────


def _prod(**kw) -> Settings:
    base = dict(
        app_env="production",
        app_secret_key="x" * 40,
        token_encryption_key=Fernet.generate_key().decode(),
        encryption_key=Fernet.generate_key().decode(),
        pii_encryption_key="",
        pii_hmac_key="h" * 64,
    )
    base.update(kw)
    return Settings(**base)


def test_exact_prod_shape_passes():
    # Prod facts: PII_ENCRYPTION_KEY="", ENCRYPTION_KEY valid Fernet, PII_HMAC_KEY 64 chars.
    _prod().validate_production()


def test_invalid_effective_encryption_key_fails():
    with pytest.raises(RuntimeError, match="not a valid Fernet key"):
        _prod(encryption_key="not-a-fernet-key").validate_production()
    with pytest.raises(RuntimeError, match="not a valid Fernet key"):
        _prod(pii_encryption_key="garbage").validate_production()


def test_valid_pii_override_passes():
    _prod(pii_encryption_key=Fernet.generate_key().decode()).validate_production()


def test_empty_hmac_with_empty_encryption_key_fails():
    with pytest.raises(RuntimeError, match="HMAC key"):
        _prod(encryption_key="", pii_hmac_key="").validate_production()


# ── engagement attribution ───────────────────────────────────────────────────


def _db_returning(attr_id):
    db = MagicMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: attr_id))
    db.commit = AsyncMock()
    return db


async def test_attribute_visitor_dedupes_per_visitor(monkeypatch):
    from apps.api.services import engagement_tracker as et

    seen: set[str] = set()

    async def fake_first(site_id, tag, visitor_id):
        key = f"{site_id}:{tag}:{visitor_id}"
        new = key not in seen
        seen.add(key)
        return new

    monkeypatch.setattr(et, "_first_sighting", fake_first)
    db = _db_returning(uuid.uuid4())
    tracker = et.EngagementTracker(db)
    assert await tracker.attribute_visitor("s1", "beam_abc", visitor_id="v1") is True
    assert await tracker.attribute_visitor("s1", "beam_abc", visitor_id="v1") is False
    assert await tracker.attribute_visitor("s1", "beam_abc", visitor_id="v2") is True
    # Increment is a single atomic UPDATE (no ORM read-modify-write).
    stmts = [str(c.args[0]) for c in db.execute.call_args_list]
    updates = [s for s in stmts if s.startswith("UPDATE")]
    assert len(updates) == 2
    assert "new_visitors_count=(engagement_attributions.new_visitors_count +" in updates[0].replace(
        " = ", "="
    ).replace("= (", "=(")


async def test_attribute_visitor_dedupe_fails_closed(monkeypatch):
    from apps.api.services import engagement_tracker as et

    def boom():
        raise ConnectionError("redis down")

    monkeypatch.setattr("apps.api.services.redis_client.get_redis", boom)
    db = _db_returning(uuid.uuid4())
    assert await et.EngagementTracker(db).attribute_visitor("s1", "beam_x", visitor_id="v") is False
    db.commit.assert_not_awaited()


async def test_attribute_visitor_unknown_tag_noop():
    from apps.api.services import engagement_tracker as et

    db = _db_returning(None)
    assert await et.EngagementTracker(db).attribute_visitor("s1", "beam_x", visitor_id="v") is False


async def test_derive_draft_site_id_scopes_visitor_lookup_to_owner():
    from apps.api.services import engagement_tracker as et

    db = MagicMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(all=lambda: []))
    await et.derive_draft_site_id(db, user_id=uuid.uuid4(), visitor_id="vis-1")
    sql = str(db.execute.call_args_list[0].args[0])
    assert "JOIN sites" in sql
    assert "sites.user_id" in sql
