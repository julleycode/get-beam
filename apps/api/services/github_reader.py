"""GitHub public-profile reader — read a visitor's PUBLIC GitHub bio + top
repositories for persona enrichment and campaign personalization.

One public source, no paid API, no login/cookie scraping: `api.github.com`'s
public REST endpoints via ``httpx``. Exactly three endpoints are ever called:

- ``GET /users/{login}``                  — profile (name, bio, company, blog, ...)
- ``GET /users/{login}/repos?sort=pushed`` — most-recently-pushed public repos
- ``GET /users/{login}/social_accounts``   — linked public social profiles

Every network call is:
- gated behind ``settings.enable_github_reader`` at the call site (default OFF);
- mock-aware — ``settings.mock_external_apis`` short-circuits to deterministic
  fake data BEFORE any cache/rate-limit/network code (CLAUDE.md: every external
  call has a mock branch);
- cached in Redis for 7 days (positive AND negative), keyed by a sha256 of the
  normalized login, so the same login isn't re-fetched across visitors/sites;
- rate-limited per clock hour, **failing CLOSED** on Redis errors (a
  rate-limiter outage must skip this optional, non-fatal enrichment rather than
  allow unbounded outbound calls — same contract as
  ``content_reader.py::_rate_ok``);
- wrapped in try/except and returns ``{}`` on any error (NON-FATAL — a GitHub
  hiccup must never break the enrichment cascade).

SECURITY / SCOPE GUARANTEES

- **Out of scope by product decision, not deferred**: this module NEVER reads
  the per-user public activity-feed endpoint, NEVER reads commit metadata, and
  NEVER touches a commit-author address field. A public bio is information the
  person chose to publish on their profile page; a commit-author address is
  frequently a personal address leaked incidentally into git metadata that the
  person did not intend to expose for outreach. Harvesting it would cross into a
  materially different kind of PII collection this repo does not do.
- **Prompt-injection defense**: every free-text field (bio, company, blog,
  location, per-repo name/description) is run through
  ``prompt_safety.clean_text()`` BEFORE it is written to ``social_context``, so
  the STORED blob is already sanitized at the source (angle brackets stripped,
  whitespace collapsed, length capped). ``sanitize_profiles()``'s
  ``_TEXT_FIELD_CAPS`` table does NOT cover these nested GitHub fields, so
  relying on it would leave them raw. Consumers that render this blob into a
  Gemini prompt must still route it through ``prompt_safety.wrap_untrusted()``
  (which independently strips angle brackets from the whole payload) — this
  module guarantees pre-sanitized input to that fence, defense-in-depth.
- **SSRF / path injection**: only ``api.github.com`` is ever contacted, checked
  against ``_GITHUB_HOSTS`` before the request is issued. The login string is
  enrichment-derived (provider-populated), so it is validated against GitHub's
  own username grammar (``_LOGIN_RE``) before being interpolated into a request
  path — a segment containing ``/`` or ``..`` is rejected and no request is
  built.
- **Credential**: reads ``settings.github_osint_token`` ONLY, never the separate
  repo-scoped ``github_token`` PAT used by the private changelog sync.
  Unauthenticated operation is supported (lower rate ceiling).

KNOWN LIMITATIONS

- Login parsing takes the LAST path segment of ``github_url``, so a repo URL
  (``github.com/octocat/some-repo``) would parse ``some-repo`` as a login. In
  practice ``EnrichmentProfile.github_url`` is provider-populated as a profile
  URL, and the username-grammar check plus a 404 catch most malformed cases.
- OSINT-derived GitHub candidates (guessed usernames from maigret/holehe, gated
  behind ``enable_osint_scan``) are deliberately NOT used as a fallback input
  here — they are a lower-confidence signal and would blur this module's
  "confirmed identity, public data only" contract. Documented future extension
  point, not implemented.
- **Sibling-clobber (pre-existing, out of scope)**: a downstream Celery-beat
  sweep (``apps/api/tasks/resolution_tasks.py``) can still wholesale-overwrite
  ``social_context`` via ``SocialIntelligence.store_social_context()`` for the
  same visitor in the same pass — destroying this module's ``github`` key along
  with pre-existing sibling keys. This module's own write is a correct
  read-modify-write merge; the sibling behavior is a pre-existing bug this plan
  does not fix. Tracked in
  ``process/features/visitors-identity/backlog/social-context-wholesale-overwrite-bug_NOTE_07-08-26.md``.

Nothing here logs raw bio/repo text or PII — only counts and coarse labels.
"""

import hashlib
import json as jsonlib
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
import structlog

from apps.api.agents.prompt_safety import clean_text
from apps.api.config import settings
from apps.api.services.redis_client import get_redis

logger = structlog.get_logger()

# Business rule: 7-day cache (same TTL as enrichment + content_reader).
GITHUB_CACHE_TTL_SECONDS = 7 * 86400
_CACHE_MISS_MARKER = "__no_github__"

# Internal hourly request cap (abuse / runaway guard), independent of GitHub's
# own quota. content_reader uses 120 for a comparable single-host budget.
_RATE_LIMIT_PER_HOUR = 100

_HTTP_TIMEOUT = 10.0

# The ONLY host this module may ever contact (G6). Checked before every request.
_GITHUB_API_BASE = "https://api.github.com"
_GITHUB_HOSTS = {"api.github.com"}

# Hosts a profile URL may legally come from, so a non-GitHub URL short-circuits
# with no network call at all (AC2).
_GITHUB_PROFILE_HOSTS = {"github.com", "www.github.com"}

# GitHub's own username grammar: alphanumeric with single internal hyphens,
# 1-39 chars. Anything else (slashes, dots, "..", overlong) is rejected BEFORE a
# request path is constructed, so a hostile enrichment value cannot inject extra
# path segments into /users/{login}/... (AC13).
_LOGIN_RE = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,38}$")

# Per-field caps for the stored blob (mirrors prompt_safety._TEXT_FIELD_CAPS
# style; these nested fields are NOT in that table — see module docstring).
_BIO_CAP = 300
_COMPANY_CAP = 120
_URLISH_CAP = 200
_REPO_NAME_CAP = 100
_REPO_DESC_CAP = 300

_USER_AGENT = "beam-github-reader/1.0 (+https://getbeam.fyi)"


# ─────────────────────────── login parsing / validation ─────────────────────


def parse_github_login(github_url: str | None) -> str | None:
    """Extract a validated GitHub login from a profile URL, else None.

    Returns None (no network call follows) when the URL is empty, is not a
    github.com URL, or when the parsed segment is not a legal GitHub username.
    Last-path-segment logic mirrors ``social_resolver._slug()`` (duplicated —
    a 4-line pure helper is not worth a cross-module import, per YAGNI).
    """
    raw = (github_url or "").strip()
    if not raw:
        return None

    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    if parsed.scheme not in ("http", "https"):
        return None
    if (parsed.hostname or "").lower() not in _GITHUB_PROFILE_HOSTS:
        return None

    # _slug()-style: last non-empty path segment, query stripped.
    seg = parsed.path.rstrip("/").split("/")[-1].split("?")[0]
    if not seg:
        return None
    if not _LOGIN_RE.match(seg):
        logger.debug("github_login_rejected_invalid_format")
        return None
    return seg


def _host_allowed(url: str) -> bool:
    """G6: reject before the network call, never after."""
    try:
        return (urlparse(url).hostname or "").lower() in _GITHUB_HOSTS
    except ValueError:
        return False


def _hash(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()


# ──────────────────────── Redis result cache (7-day TTL) ────────────────────


async def _cache_get(key: str) -> tuple[bool, dict | None]:
    """(hit, data) — data is None on a negative-cache hit.
    Redis failures degrade to a miss; caching is best-effort."""
    try:
        raw = await get_redis().get(key)
    except Exception:
        return (False, None)
    if raw is None:
        return (False, None)
    if raw == _CACHE_MISS_MARKER:
        return (True, None)
    try:
        return (True, jsonlib.loads(raw))
    except (ValueError, TypeError):
        return (False, None)


async def _cache_set(key: str, data: dict | None, ttl: int = GITHUB_CACHE_TTL_SECONDS) -> None:
    try:
        raw = _CACHE_MISS_MARKER if data is None else jsonlib.dumps(data, default=str)
        await get_redis().set(key, raw, ex=ttl)
    except Exception:
        logger.debug("github_cache_set_failed")


# ──────────────────────────── hourly rate limit ─────────────────────────────


async def _rate_ok() -> bool:
    """Reserve one request in the current clock hour.

    Returns True when within the cap, False when the cap is reached. Fails
    CLOSED (returns False) on any Redis error: a rate-limiter outage must skip
    this optional, non-fatal enrichment rather than allow unbounded outbound
    calls (same contract as ``content_reader._rate_ok``).
    """
    try:
        redis = get_redis()
        hour = datetime.now(timezone.utc).strftime("%Y%m%d%H")
        key = f"github_rate:{hour}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 3600)
        if count > _RATE_LIMIT_PER_HOUR:
            await redis.decr(key)
            return False
        return True
    except Exception as exc:
        logger.warning("github_rate_limiter_failed_closed", error=str(exc)[:120])
        return False


# ──────────────────────────── mock fixture ──────────────────────────────────


def _mock_github(login: str) -> dict:
    return {
        "login": login,
        "name": "Mock Octocat",
        "bio": "A mock GitHub profile for testing.",
        "company": "@mockcorp",
        "blog": "https://example.com",
        "location": "Mockville",
        "followers": 42,
        "public_repos": 7,
        "hireable": True,
        "dominant_languages": ["Python", "TypeScript"],
        "top_repos": [
            {
                "name": "mock-repo",
                "language": "Python",
                "stars": 12,
                "description": "A mock repository.",
                "pushed_at": "2026-06-30T00:00:00Z",
            }
        ],
        "social_accounts": [{"provider": "twitter", "url": "https://twitter.com/mock"}],
        "fetched_at": "2026-01-01T00:00:00+00:00",
    }


# ──────────────────────────── response shaping ──────────────────────────────


def _shape_repos(payload: object, max_repos: int) -> tuple[list[dict], list[str]]:
    """Return (top_repos, dominant_languages) from a /repos response body.

    Forks are kept (a fork-heavy account still signals interest), but every
    free-text field is sanitized here, at the source.
    """
    if not isinstance(payload, list):
        return ([], [])

    top: list[dict] = []
    lang_counts: dict[str, int] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not name:
            continue
        language = item.get("language")
        if isinstance(language, str) and language.strip():
            lang = clean_text(language, 40)
            if lang:
                lang_counts[lang] = lang_counts.get(lang, 0) + 1
        else:
            lang = None
        if len(top) < max_repos:
            top.append({
                "name": clean_text(str(name), _REPO_NAME_CAP),
                "language": lang,
                "stars": item.get("stargazers_count"),
                "description": clean_text(str(item.get("description") or ""), _REPO_DESC_CAP) or None,
                "pushed_at": item.get("pushed_at"),
            })

    dominant = sorted(lang_counts, key=lambda k: (-lang_counts[k], k))[:5]
    return (top, dominant)


def _shape_social_accounts(payload: object) -> list[dict]:
    if not isinstance(payload, list):
        return []
    out: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not url:
            continue
        out.append({
            "provider": clean_text(str(item.get("provider") or "other"), 40),
            "url": clean_text(str(url), _URLISH_CAP),
        })
        if len(out) >= 10:
            break
    return out


def _shape_summary(
    login: str, profile: dict, repos_payload: object, social_payload: object, max_repos: int
) -> dict:
    """Build the stored ``social_context["github"]`` blob.

    EVERY free-text value passes through ``clean_text()`` here (G2) so the
    persisted blob is already sanitized regardless of who reads it later.
    """
    top_repos, dominant_languages = _shape_repos(repos_payload, max_repos)
    return {
        "login": login,
        "name": clean_text(str(profile.get("name") or ""), _COMPANY_CAP) or None,
        "bio": clean_text(str(profile.get("bio") or ""), _BIO_CAP) or None,
        "company": clean_text(str(profile.get("company") or ""), _COMPANY_CAP) or None,
        "blog": clean_text(str(profile.get("blog") or ""), _URLISH_CAP) or None,
        "location": clean_text(str(profile.get("location") or ""), _URLISH_CAP) or None,
        "followers": profile.get("followers"),
        "public_repos": profile.get("public_repos"),
        "hireable": profile.get("hireable"),
        "dominant_languages": dominant_languages,
        "top_repos": top_repos,
        "social_accounts": _shape_social_accounts(social_payload),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


# ──────────────────────────── public entrypoint ─────────────────────────────


def _headers() -> dict[str, str]:
    """Auth header uses ``github_osint_token`` ONLY (G4) — never the private
    changelog-sync PAT."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": _USER_AGENT,
    }
    token = settings.github_osint_token
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _quota_exhausted(resp: httpx.Response) -> bool:
    """True when GitHub says this credential has no quota left (G8)."""
    remaining = resp.headers.get("X-RateLimit-Remaining")
    if remaining is None:
        return False
    try:
        return int(remaining) <= 0
    except ValueError:
        return False


async def fetch_github_profile(
    github_url: str | None, *, http_client: httpx.AsyncClient | None = None
) -> dict:
    """Read a public GitHub profile + top repos for ``github_url``.

    Returns the ``social_context["github"]`` blob, or ``{}`` on empty/invalid
    URL, unknown login, rate limit, quota exhaustion, or ANY error. Never
    raises (NON-FATAL). Cached 7 days (positive + negative). Honors
    ``settings.mock_external_apis``.
    """
    try:
        login = parse_github_login(github_url)
        if not login:
            return {}

        if settings.mock_external_apis:
            return _mock_github(login)

        cache_key = f"github:profile:{_hash(login)}"
        hit, cached = await _cache_get(cache_key)
        if hit:
            logger.debug("github_cache_hit", match=cached is not None)
            return cached or {}

        if not await _rate_ok():
            logger.warning("github_rate_limited")
            # Brief negative marker — avoid a per-visitor retry storm.
            await _cache_set(cache_key, None, ttl=300)
            return {}

        max_repos = max(1, settings.github_reader_max_repos)
        profile_url = f"{_GITHUB_API_BASE}/users/{login}"
        repos_url = f"{_GITHUB_API_BASE}/users/{login}/repos"
        social_url = f"{_GITHUB_API_BASE}/users/{login}/social_accounts"

        # G6: allowlist check BEFORE any network call, for every URL built.
        for url in (profile_url, repos_url, social_url):
            if not _host_allowed(url):
                logger.warning("github_host_not_allowed")
                return {}

        owns_client = http_client is None
        client = http_client or httpx.AsyncClient(timeout=_HTTP_TIMEOUT)
        try:
            headers = _headers()
            resp = await client.get(profile_url, headers=headers)

            if resp.status_code == 404:
                logger.debug("github_login_not_found")
                await _cache_set(cache_key, None)  # negative-cache 7d (AC3/AC8)
                return {}
            if resp.status_code == 403:
                # Secondary rate limit / abuse detection. Do NOT retry inline and
                # do NOT negative-cache — the login is probably fine.
                logger.warning(
                    "github_forbidden_rate_limited",
                    retry_after=resp.headers.get("Retry-After"),
                )
                return {}
            if resp.status_code == 429:
                logger.warning("github_throttled", status=resp.status_code)
                return {}
            if _quota_exhausted(resp):
                logger.warning("github_quota_exhausted")
                return {}
            if resp.status_code != 200:
                logger.warning("github_profile_error", status=resp.status_code)
                return {}

            try:
                profile_payload = resp.json()
            except ValueError:
                return {}
            if not isinstance(profile_payload, dict):
                return {}

            repos_payload: object = []
            social_payload: object = []
            try:
                r_resp = await client.get(
                    repos_url,
                    headers=headers,
                    params={"sort": "pushed", "per_page": max_repos},
                )
                if r_resp.status_code == 200:
                    repos_payload = r_resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.debug("github_repos_skipped", error=str(exc)[:120])

            try:
                s_resp = await client.get(social_url, headers=headers)
                if s_resp.status_code == 200:
                    social_payload = s_resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.debug("github_social_skipped", error=str(exc)[:120])
        finally:
            if owns_client:
                await client.aclose()

        summary = _shape_summary(login, profile_payload, repos_payload, social_payload, max_repos)
        await _cache_set(cache_key, summary)
        logger.info(
            "github_profile_ok",
            repos=len(summary.get("top_repos") or []),
            languages=len(summary.get("dominant_languages") or []),
        )
        return summary

    except httpx.HTTPError as exc:
        # Transient network error — non-fatal, do NOT negative-cache.
        logger.warning("github_http_error", error=str(exc)[:200])
        return {}
    except Exception as exc:
        logger.warning("github_reader_failed", error=str(exc)[:200])
        return {}
