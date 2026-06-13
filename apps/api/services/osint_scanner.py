"""Free, stackable OSINT email→account scanner.

Given an email, runs one or more free OSINT engines that check which sites the
email is registered on (password-reset / registration enumeration — the holehe
methodology). Results are normalized into `OsintAccount` rows and merged.

Engines today (stack more by adding an adapter to ``_ADAPTER_REGISTRY``):
  - user-scanner (PyPI ``user-scanner``): 103 sites / 18 categories. Returns a
    rich ``extra`` (username, joined date, avatar) for many sites.
  - holehe (PyPI ``holehe``): 121 sites. Existence-only (+ masked
    emailrecovery / phoneNumber hints when a site leaks them).

Design notes:
  - Manual, per-visitor trigger only (cost/abuse control lives in the endpoint).
  - Every outbound check is bounded by a shared ``asyncio.Semaphore`` AND an
    overall monotonic wall-clock deadline, so a scan can never run unbounded
    from a shared cloud IP. Past the deadline, queued checks short-circuit and
    we return partial results.
  - Adapters MUST NOT raise — they log and return an empty :class:`AdapterResult`.
  - Results are cached in Redis by email hash (7-day TTL) so re-scanning the
    same person is instant and free.
  - Ethics: account-existence checks rely on public reset/registration signals
    (OSINT) — a legal gray area under some sites' ToS. Use responsibly.
"""

from __future__ import annotations

import asyncio
import hashlib
import json as jsonlib
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable

import httpx
import structlog

from apps.api.config import settings
from apps.api.services.redis_client import get_redis

logger = structlog.get_logger()

# Cache OSINT scans for 7 days — existence is slow-changing and scans are slow.
OSINT_CACHE_TTL_SECONDS = 7 * 86400
_CACHE_PREFIX = "osint:scan:"


# ──────────────────────────── normalized result ────────────────────────────


@dataclass
class OsintAccount:
    """One discovered account, normalized across engines."""

    site_name: str
    category: str | None
    url: str | None  # site base URL (or profile URL if the engine gave one)
    kind: str  # "profile" (a real handle/username surfaced) | "registered"
    confidence: str  # "confirmed" (real engine data) | "likely" | "guess"
    source_engine: str  # "user-scanner" | "holehe" | comma-joined after merge
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AdapterResult:
    """What one engine returns from a scan."""

    engine: str
    accounts: list[OsintAccount] = field(default_factory=list)
    checked: int = 0  # modules actually run to completion
    total: int = 0  # modules the engine would run with unlimited time
    partial: bool = False  # hit the wall-clock cap before finishing


# ──────────────────────────── adapter base ────────────────────────────


class OsintAdapter:
    """Base adapter. Subclasses implement ``_available`` and ``scan``."""

    name: str = "base"

    def is_available(self) -> bool:
        """True if the underlying library imported cleanly."""
        try:
            return self._available()
        except Exception:
            return False

    def _available(self) -> bool:  # pragma: no cover - overridden
        return False

    async def scan(
        self,
        email: str,
        *,
        semaphore: asyncio.Semaphore,
        per_module_timeout: float,
        deadline: float,
        skip_categories: set[str],
    ) -> AdapterResult:  # pragma: no cover - overridden
        return AdapterResult(engine=self.name)


async def _bounded_check(
    semaphore: asyncio.Semaphore,
    deadline: float,
    per_module_timeout: float,
    coro_factory: Callable[[], Awaitable],
):
    """Run one check under the semaphore, bounded by per-module timeout AND the
    overall deadline. Returns the coro result, or None if it timed out, errored,
    or the deadline already passed. Never raises."""
    async with semaphore:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None  # deadline blown while queued — short-circuit
        timeout = min(per_module_timeout, remaining)
        try:
            return await asyncio.wait_for(coro_factory(), timeout)
        except Exception:
            return None


# ──────────────────────────── user-scanner ────────────────────────────


class UserScannerAdapter(OsintAdapter):
    name = "user-scanner"

    def _available(self) -> bool:
        from user_scanner.core import engine  # noqa: F401

        return True

    async def scan(
        self,
        email: str,
        *,
        semaphore: asyncio.Semaphore,
        per_module_timeout: float,
        deadline: float,
        skip_categories: set[str],
    ) -> AdapterResult:
        result = AdapterResult(engine=self.name)
        try:
            from user_scanner.core import engine
        except Exception as e:
            logger.warning("osint_user_scanner_import_failed", err=str(e))
            return result

        # Built-in registry: categories→Path, NSFW already excluded by no_nsfw.
        try:
            categories = engine.load_categories(is_email=True, no_nsfw=True)
        except Exception as e:
            logger.warning("osint_user_scanner_categories_failed", err=str(e))
            return result

        modules = []
        for cat_name, cat_path in categories.items():
            if cat_name.lower() in skip_categories:
                continue
            try:
                modules.extend(engine.load_modules(cat_path))
            except Exception:
                continue
        result.total = len(modules)

        async def run_module(module):
            res = await _bounded_check(
                semaphore, deadline, per_module_timeout,
                lambda: engine.check(module, email),
            )
            if res is None:
                return None
            return _map_user_scanner_result(res)

        gathered = await asyncio.gather(
            *(run_module(m) for m in modules), return_exceptions=True
        )
        for item in gathered:
            if isinstance(item, OsintAccount):
                result.accounts.append(item)
                result.checked += 1
            elif item is None:
                # ran but not found, OR skipped past deadline; can't tell apart
                # cheaply, so treat "we got a verdict" as checked only for hits.
                result.checked += 0
        # partial if fewer modules produced a definitive run than total and the
        # deadline was hit.
        result.partial = time.monotonic() >= deadline and result.total > 0
        logger.info(
            "osint_user_scanner_done",
            email_prefix=email[:5],
            total=result.total,
            hits=len(result.accounts),
            partial=result.partial,
        )
        return result


def _map_user_scanner_result(res) -> OsintAccount | None:
    """Map a user_scanner Result → OsintAccount, or None if not registered."""
    try:
        data = res.to_dict() if hasattr(res, "to_dict") else {}
    except Exception:
        data = {}
    status = (data.get("status") or getattr(res, "status", "") or "").lower()
    is_found = bool(getattr(res, "is_found", False)) or status == "registered"
    if not is_found:
        return None
    extra_raw = data.get("extra") or getattr(res, "extra", None) or {}
    # Keep a safe, useful subset of the rich extra (avoid storing huge blobs).
    keep = ("username", "name", "joined", "avatar", "url", "id", "is_seller")
    extra = {k: extra_raw[k] for k in keep if isinstance(extra_raw, dict) and extra_raw.get(k)}
    username = extra.get("username") or extra.get("name")
    return OsintAccount(
        site_name=data.get("site_name") or getattr(res, "site_name", "?"),
        category=data.get("category") or getattr(res, "category", None),
        url=data.get("url") or getattr(res, "url", None),
        kind="profile" if username else "registered",
        confidence="confirmed",
        source_engine="user-scanner",
        extra=extra,
    )


# ──────────────────────────── holehe ────────────────────────────

# get_functions imports 121 modules; cache the list across scans.
_holehe_funcs: list | None = None


class HoleheAdapter(OsintAdapter):
    name = "holehe"

    def _available(self) -> bool:
        from holehe.core import get_functions, import_submodules  # noqa: F401

        return True

    def _load_funcs(self) -> list:
        global _holehe_funcs
        if _holehe_funcs is None:
            from holehe.core import get_functions, import_submodules

            _holehe_funcs = get_functions(import_submodules("holehe.modules"))
        return _holehe_funcs

    @staticmethod
    def _category(func) -> str:
        parts = getattr(func, "__module__", "").split(".")
        return parts[2] if len(parts) > 3 else "?"  # holehe.modules.<cat>.<site>

    async def scan(
        self,
        email: str,
        *,
        semaphore: asyncio.Semaphore,
        per_module_timeout: float,
        deadline: float,
        skip_categories: set[str],
    ) -> AdapterResult:
        result = AdapterResult(engine=self.name)
        try:
            funcs = [f for f in self._load_funcs() if self._category(f).lower() not in skip_categories]
        except Exception as e:
            logger.warning("osint_holehe_load_failed", err=str(e))
            return result
        result.total = len(funcs)

        # holehe modules share one client; bound each call too.
        async with httpx.AsyncClient(
            timeout=per_module_timeout,
            headers={"User-Agent": "Mozilla/5.0"},
            follow_redirects=True,
        ) as client:

            async def run_func(func):
                out: list[dict] = []

                async def _call():
                    await func(email, client, out)
                    return out

                res = await _bounded_check(
                    semaphore, deadline, per_module_timeout, _call
                )
                if not res:
                    return None
                return _map_holehe_out(res, self._category(func))

            gathered = await asyncio.gather(
                *(run_func(f) for f in funcs), return_exceptions=True
            )

        for item in gathered:
            if isinstance(item, OsintAccount):
                result.accounts.append(item)
                result.checked += 1
        result.partial = time.monotonic() >= deadline and result.total > 0
        logger.info(
            "osint_holehe_done",
            email_prefix=email[:5],
            total=result.total,
            hits=len(result.accounts),
            partial=result.partial,
        )
        return result


def _map_holehe_out(out: list[dict], category: str) -> OsintAccount | None:
    """Map a holehe `out` list → OsintAccount, or None if not registered."""
    if not out:
        return None
    entry = out[0]
    if not entry.get("exists"):
        return None
    domain = entry.get("domain") or ""
    extra = {}
    for k in ("emailrecovery", "phoneNumber", "others"):
        if entry.get(k):
            extra[k] = entry[k]
    return OsintAccount(
        site_name=entry.get("name") or domain or "?",
        category=category,
        url=f"https://{domain}" if domain else None,
        kind="registered",
        confidence="confirmed",
        source_engine="holehe",
        extra=extra,
    )


# ──────────────────────────── registry + orchestrator ────────────────────────────

_ADAPTER_REGISTRY: dict[str, Callable[[], OsintAdapter]] = {
    "user-scanner": UserScannerAdapter,
    "holehe": HoleheAdapter,
    # Future free/paid engines plug in here, no caller changes:
    # "sherlock": SherlockAdapter, "osint-industries": OsintIndustriesAdapter,
}

# Engine names that are valid in ``settings.osint_engines`` but are NOT email-scan
# adapters — they belong to a later pipeline stage (social_resolver). Listed here
# so get_scanners() skips them silently instead of warning "unknown engine".
_PIPELINE_ONLY_ENGINES = frozenset({"maigret"})


def get_scanners() -> list[OsintAdapter]:
    """Enabled + importable adapters, per ``settings.osint_engines``."""
    enabled = [e.strip() for e in settings.osint_engines.split(",") if e.strip()]
    adapters: list[OsintAdapter] = []
    for name in enabled:
        if name in _PIPELINE_ONLY_ENGINES:
            continue  # handled in social_resolver, not an email-scan adapter
        factory = _ADAPTER_REGISTRY.get(name)
        if factory is None:
            logger.warning("osint_unknown_engine", engine=name)
            continue
        adapter = factory()
        if adapter.is_available():
            adapters.append(adapter)
        else:
            logger.warning("osint_engine_unavailable", engine=name)
    return adapters


def _dedupe(accounts: list[OsintAccount]) -> list[OsintAccount]:
    """Collapse by site_name (case-insensitive). Prefer the richer row
    (a profile/handle over a bare registration); merge source_engine labels."""
    by_site: dict[str, OsintAccount] = {}
    for acc in accounts:
        key = (acc.site_name or "").strip().lower()
        if not key:
            continue
        existing = by_site.get(key)
        if existing is None:
            by_site[key] = acc
            continue
        # Merge engine labels.
        engines = sorted({existing.source_engine, acc.source_engine})
        winner = acc if (_richness(acc) > _richness(existing)) else existing
        merged = OsintAccount(
            site_name=winner.site_name,
            category=winner.category or existing.category or acc.category,
            url=winner.url or existing.url or acc.url,
            kind="profile" if "profile" in (existing.kind, acc.kind) else "registered",
            confidence=winner.confidence,
            source_engine=",".join(engines),
            extra={**existing.extra, **acc.extra},
        )
        by_site[key] = merged
    return list(by_site.values())


def _richness(acc: OsintAccount) -> int:
    score = len(acc.extra or {})
    if acc.kind == "profile":
        score += 5
    return score


def _cache_key(email: str) -> str:
    digest = hashlib.sha256(email.strip().lower().encode()).hexdigest()
    return f"{_CACHE_PREFIX}{digest}"


async def _cache_get(email: str) -> dict | None:
    try:
        raw = await get_redis().get(_cache_key(email))
    except Exception:
        return None
    if not raw:
        return None
    try:
        return jsonlib.loads(raw)
    except (ValueError, TypeError):
        return None


async def _cache_set(email: str, blob: dict) -> None:
    try:
        await get_redis().set(
            _cache_key(email), jsonlib.dumps(blob, default=str),
            ex=OSINT_CACHE_TTL_SECONDS,
        )
    except Exception:
        logger.debug("osint_cache_set_failed", email_prefix=email[:5])


async def run_osint_scan(email: str) -> dict:
    """Run all enabled engines against ``email`` and return the ``osint_scan`` blob.

    Idempotent: a 7-day Redis cache means re-scanning the same email is instant.
    Never raises — returns a blob with a ``status`` field the UI renders.
    """
    email = (email or "").strip()
    if not email:
        return {"status": "skipped_no_email", "accounts": [], "engines": [],
                "summary": {}, "message": "No email to scan."}

    cached = await _cache_get(email)
    if cached is not None:
        cached = {**cached, "status": "cached"}
        return cached

    adapters = get_scanners()
    if not adapters:
        return {
            "status": "error", "accounts": [], "engines": [], "summary": {},
            "message": "No OSINT engine available (library missing or all disabled).",
        }

    semaphore = asyncio.Semaphore(max(1, settings.osint_scan_concurrency))
    deadline = time.monotonic() + settings.osint_scan_wall_clock_cap
    skip = {c.strip().lower() for c in settings.osint_scan_skip_categories.split(",") if c.strip()}

    adapter_results: list[AdapterResult] = await asyncio.gather(
        *(
            a.scan(
                email,
                semaphore=semaphore,
                per_module_timeout=settings.osint_scan_per_module_timeout,
                deadline=deadline,
                skip_categories=skip,
            )
            for a in adapters
        )
    )

    all_accounts: list[OsintAccount] = []
    for r in adapter_results:
        all_accounts.extend(r.accounts)
    accounts = _dedupe(all_accounts)

    profile_count = sum(1 for a in accounts if a.kind == "profile")
    registered_count = len(accounts)
    partial = any(r.partial for r in adapter_results)
    checked = sum(r.checked for r in adapter_results)
    total = sum(r.total for r in adapter_results)

    blob = {
        "status": "complete",
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "engines": [r.engine for r in adapter_results],
        "accounts": [a.to_dict() for a in accounts],
        "summary": {
            "registered_count": registered_count,
            "profile_count": profile_count,
            "checked": checked,
            "total": total,
            "partial": partial,
            "skipped_categories": sorted(skip),
        },
        "message": (
            f"Found {profile_count} profile(s) with details and "
            f"{registered_count} site registration(s)."
            + (" (partial — time cap reached)" if partial else "")
        ),
    }

    await _cache_set(email, blob)
    logger.info(
        "osint_scan_complete", email_prefix=email[:5],
        engines=blob["engines"], registered=registered_count,
        profiles=profile_count, partial=partial,
    )
    return blob
