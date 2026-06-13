"""Unit tests for the OSINT scanner service (no DB, no network).

Covers the orchestration logic — engine selection, result mapping,
dedup-by-site, blob shape, and graceful degradation — with stub adapters.
"""

import asyncio

import pytest

from apps.api.services import osint_scanner as osc
from apps.api.services.osint_scanner import (
    AdapterResult,
    OsintAccount,
    OsintAdapter,
    _dedupe,
    _map_holehe_out,
    _map_user_scanner_result,
    run_osint_scan,
)


# ──────────────────────── result mapping ────────────────────────


class _FakeUSResult:
    """Mimic a user_scanner Result with a to_dict() and attrs."""

    def __init__(self, data, is_found=True):
        self._data = data
        self.is_found = is_found
        self.status = data.get("status", "")
        self.site_name = data.get("site_name", "")
        self.category = data.get("category")
        self.url = data.get("url")
        self.extra = data.get("extra", {})

    def to_dict(self):
        return self._data


def test_map_user_scanner_registered_with_username_is_profile():
    res = _FakeUSResult({
        "status": "Registered", "site_name": "Etsy", "category": "Shopping",
        "url": "https://etsy.com",
        "extra": {"username": "jdoe", "joined": "2020-01-01", "avatar": "x", "junk": "drop"},
    })
    acc = _map_user_scanner_result(res)
    assert acc is not None
    assert acc.kind == "profile"  # username present
    assert acc.confidence == "confirmed"
    assert acc.source_engine == "user-scanner"
    assert acc.site_name == "Etsy"
    assert acc.extra["username"] == "jdoe"
    assert "junk" not in acc.extra  # only the safe subset is kept


def test_map_user_scanner_registered_without_username_is_registered():
    res = _FakeUSResult({
        "status": "Registered", "site_name": "Spotify", "url": None, "extra": {},
    })
    acc = _map_user_scanner_result(res)
    assert acc is not None
    assert acc.kind == "registered"


def test_map_user_scanner_not_found_is_none():
    res = _FakeUSResult({"status": "Not Registered", "site_name": "Nope"}, is_found=False)
    assert _map_user_scanner_result(res) is None


def test_map_holehe_exists_true():
    out = [{"name": "Discord", "domain": "discord.com", "exists": True,
            "emailrecovery": "j***@gmail.com", "phoneNumber": None, "others": None}]
    acc = _map_holehe_out(out, "social_media")
    assert acc is not None
    assert acc.site_name == "Discord"
    assert acc.url == "https://discord.com"
    assert acc.kind == "registered"
    assert acc.source_engine == "holehe"
    assert acc.extra["emailrecovery"] == "j***@gmail.com"


def test_map_holehe_exists_false_is_none():
    assert _map_holehe_out([{"name": "X", "domain": "x.com", "exists": False}], "social_media") is None
    assert _map_holehe_out([], "social_media") is None


# ──────────────────────── dedup ────────────────────────


def test_dedupe_collapses_same_site_prefers_profile():
    accounts = [
        OsintAccount("GitHub", "dev", "https://github.com", "registered", "confirmed", "holehe", {}),
        OsintAccount("github", "dev", "https://github.com/jdoe", "profile", "confirmed",
                     "user-scanner", {"username": "jdoe"}),
    ]
    out = _dedupe(accounts)
    assert len(out) == 1
    merged = out[0]
    assert merged.kind == "profile"
    assert merged.source_engine == "holehe,user-scanner"  # merged + sorted
    assert merged.extra.get("username") == "jdoe"


def test_dedupe_keeps_distinct_sites():
    accounts = [
        OsintAccount("GitHub", "dev", None, "registered", "confirmed", "holehe", {}),
        OsintAccount("Etsy", "shopping", None, "registered", "confirmed", "holehe", {}),
    ]
    assert len(_dedupe(accounts)) == 2


# ──────────────────────── orchestrator ────────────────────────


class _StubAdapter(OsintAdapter):
    def __init__(self, name, accounts, total=10, partial=False):
        self.name = name
        self._accounts = accounts
        self._total = total
        self._partial = partial

    def _available(self):
        return True

    async def scan(self, email, **kwargs):
        return AdapterResult(
            engine=self.name, accounts=self._accounts,
            checked=len(self._accounts), total=self._total, partial=self._partial,
        )


@pytest.fixture(autouse=True)
def _no_cache(monkeypatch):
    """Disable Redis cache so unit tests never touch the network."""
    async def _miss(_email):
        return None

    async def _noop(_email, _blob):
        return None

    monkeypatch.setattr(osc, "_cache_get", _miss)
    monkeypatch.setattr(osc, "_cache_set", _noop)


@pytest.mark.asyncio
async def test_run_scan_builds_blob(monkeypatch):
    us_acc = OsintAccount("Etsy", "shopping", "https://etsy.com", "profile", "confirmed",
                          "user-scanner", {"username": "jdoe"})
    h_acc = OsintAccount("Etsy", "shopping", "https://etsy.com", "registered", "confirmed",
                         "holehe", {})  # dup site → should collapse
    h_acc2 = OsintAccount("Discord", "social", "https://discord.com", "registered",
                          "confirmed", "holehe", {})
    monkeypatch.setattr(osc, "get_scanners", lambda: [
        _StubAdapter("user-scanner", [us_acc], total=100),
        _StubAdapter("holehe", [h_acc, h_acc2], total=120, partial=True),
    ])

    blob = await run_osint_scan("jdoe@example.com")
    assert blob["status"] == "complete"
    assert blob["engines"] == ["user-scanner", "holehe"]
    # Etsy collapsed → Discord + Etsy = 2 accounts
    assert blob["summary"]["registered_count"] == 2
    assert blob["summary"]["profile_count"] == 1  # Etsy is profile
    assert blob["summary"]["partial"] is True
    assert blob["summary"]["total"] == 220
    sites = {a["site_name"] for a in blob["accounts"]}
    assert sites == {"Etsy", "Discord"}


@pytest.mark.asyncio
async def test_run_scan_empty_email():
    blob = await run_osint_scan("   ")
    assert blob["status"] == "skipped_no_email"
    assert blob["accounts"] == []


@pytest.mark.asyncio
async def test_run_scan_no_adapters_is_error(monkeypatch):
    monkeypatch.setattr(osc, "get_scanners", lambda: [])
    blob = await run_osint_scan("x@example.com")
    assert blob["status"] == "error"
    assert "engine" in blob["message"].lower()


def test_get_scanners_respects_engine_flag_and_availability(monkeypatch):
    monkeypatch.setattr(osc.settings, "osint_engines", "holehe")
    # Force both adapters "available" so only the flag filters.
    monkeypatch.setattr(osc.UserScannerAdapter, "_available", lambda self: True)
    monkeypatch.setattr(osc.HoleheAdapter, "_available", lambda self: True)
    names = [a.name for a in osc.get_scanners()]
    assert names == ["holehe"]  # user-scanner excluded by config


def test_get_scanners_drops_unavailable(monkeypatch):
    monkeypatch.setattr(osc.settings, "osint_engines", "user-scanner,holehe")
    monkeypatch.setattr(osc.UserScannerAdapter, "_available", lambda self: True)
    monkeypatch.setattr(osc.HoleheAdapter, "_available", lambda self: False)  # lib missing
    names = [a.name for a in osc.get_scanners()]
    assert names == ["user-scanner"]


def test_get_scanners_skips_maigret_silently(monkeypatch):
    """maigret is a username-stage engine (social_resolver), not an email-scan
    adapter — get_scanners() must skip it WITHOUT a spurious unknown-engine warn.
    This matches the new config default 'user-scanner,holehe,maigret'."""
    monkeypatch.setattr(osc.settings, "osint_engines", "user-scanner,holehe,maigret")
    monkeypatch.setattr(osc.UserScannerAdapter, "_available", lambda self: True)
    monkeypatch.setattr(osc.HoleheAdapter, "_available", lambda self: True)

    warnings: list[tuple] = []
    monkeypatch.setattr(osc.logger, "warning", lambda *a, **k: warnings.append((a, k)))

    names = [a.name for a in osc.get_scanners()]
    assert names == ["user-scanner", "holehe"]  # maigret not an email adapter
    # no "unknown engine" warning for the pipeline-only name
    assert not any(a and a[0] == "osint_unknown_engine" for a, _ in warnings)
    assert "maigret" in osc._PIPELINE_ONLY_ENGINES


def test_adapter_is_available_swallows_import_error(monkeypatch):
    def boom(self):
        raise ImportError("no module")

    monkeypatch.setattr(osc.UserScannerAdapter, "_available", boom)
    assert osc.UserScannerAdapter().is_available() is False
