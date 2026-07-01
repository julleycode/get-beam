"""Content reader — read PUBLIC YouTube + Reddit content for persona enrichment
and campaign personalization.

Two public sources, no paid API and no login/cookie scraping:
- YouTube: the ``yt-dlp`` library (metadata only — title/description + recent
  video titles/dates; never downloads video/audio). ``yt-dlp`` is synchronous,
  so every call is wrapped in ``asyncio.to_thread`` to stay non-blocking.
- Reddit: reddit.com's public ``.json`` endpoints via ``httpx`` (no ``praw``).

Every network call is:
- gated behind ``settings.enable_content_reader`` at the call sites (P2/P3/P4);
- mock-aware — ``settings.mock_external_apis`` short-circuits to deterministic
  fake data (CLAUDE.md: every external call has a mock branch);
- cached in Redis for 7 days (positive AND negative), keyed by a sha256 of the
  normalized input so the same handle isn't re-fetched across visitors/sites;
- rate-limited per source per clock hour (fails open on Redis errors);
- wrapped in try/except and returns ``{}`` on any error (NON-FATAL — a YouTube
  or Reddit hiccup must never break enrichment or campaign planning).

Nothing here logs raw post/video content or PII — only counts and coarse labels.
"""

import asyncio
import hashlib
import json as jsonlib
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog

from apps.api.config import settings
from apps.api.services.redis_client import get_redis

logger = structlog.get_logger()

# Business rule: cache content-reader results for 7 days (same TTL as enrichment).
# Company channels change rarely, so P4 uses a longer TTL (see below).
CONTENT_CACHE_TTL_SECONDS = 7 * 86400
COMPANY_CHANNEL_CACHE_TTL_SECONDS = 30 * 86400  # P4: company channels are stable
_CACHE_MISS_MARKER = "__no_content__"

# Per-source hourly request cap (abuse / runaway guard). Reddit's public JSON
# endpoints throttle aggressively; keep this conservative.
_RATE_LIMIT_PER_HOUR = 120

# Descriptive User-Agent — reddit blocks generic/default agents with 429/403.
_REDDIT_USER_AGENT = "web:beam-content-reader:v1 (+https://getbeam.fyi)"

# Only these hosts may ever be fetched by yt-dlp. A URL whose host is NOT here
# is rejected BEFORE it reaches yt-dlp, so an attacker-controlled enrichment
# field like "http://169.254.169.254/youtube.com" (cloud metadata SSRF) or
# "file:///etc/passwd#youtube.com" can never trigger a fetch of an unintended
# target via yt-dlp's generic extractor.
_YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "music.youtube.com", "youtu.be",
}
_HANDLE_RE = re.compile(r"[A-Za-z0-9._-]{1,80}")


def _safe_youtube_query(target: str) -> str | None:
    """Turn ``target`` into a safe yt-dlp query, or None if it is not a
    trustworthy YouTube handle/URL.

    SSRF guard: URL-shaped input is accepted ONLY when its host is a real
    YouTube host over http(s); everything else is rejected. Bare input must be
    a plain ``@handle``/``handle`` (no scheme, no slash).
    """
    t = (target or "").strip()
    if not t:
        return None
    if "://" in t or "/" in t or t.lower().startswith("www."):
        parsed = urlparse(t if "://" in t else f"https://{t}")
        if parsed.scheme not in ("http", "https"):
            return None
        if (parsed.hostname or "").lower() not in _YOUTUBE_HOSTS:
            return None
        return parsed.geturl()
    handle = t.lstrip("@")
    if not _HANDLE_RE.fullmatch(handle):
        return None
    return f"https://www.youtube.com/@{handle}/videos"


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


async def _cache_set(key: str, data: dict | None, ttl: int = CONTENT_CACHE_TTL_SECONDS) -> None:
    try:
        raw = _CACHE_MISS_MARKER if data is None else jsonlib.dumps(data, default=str)
        await get_redis().set(key, raw, ex=ttl)
    except Exception:
        logger.debug("content_cache_set_failed", key=key)


# ──────────────────────── Per-source hourly rate limit ──────────────────────


async def _rate_ok(source: str) -> bool:
    """Reserve one request for ``source`` in the current clock hour.

    Returns True when within the cap, False when the cap is reached. Fails
    CLOSED (returns False) on any Redis error: this path drives outbound
    yt-dlp/Reddit fetches and paid Gemini calls, so a rate-limiter outage must
    skip the (optional, non-fatal) enrichment rather than allow unbounded calls.
    """
    try:
        redis = get_redis()
        hour = datetime.now(timezone.utc).strftime("%Y%m%d%H")
        key = f"content_rate:{source}:{hour}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 3600)
        if count > _RATE_LIMIT_PER_HOUR:
            await redis.decr(key)
            return False
        return True
    except Exception as exc:
        logger.warning("content_rate_limiter_failed_closed", source=source, error=str(exc)[:120])
        return False


def _hash(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()


# ──────────────────────────── Mock fixtures ─────────────────────────────────


def _mock_youtube(target: str) -> dict:
    return {
        "source": "youtube",
        "channel_title": "Mock Channel",
        "description": "A mock YouTube channel for testing.",
        "url": f"https://www.youtube.com/@{target.strip().lstrip('@')[:40]}",
        "recent_videos": [
            {"title": "Mock video one", "published": "2026-06-30", "url": "https://youtu.be/mock1"},
            {"title": "Mock video two", "published": "2026-06-25", "url": "https://youtu.be/mock2"},
        ],
    }


def _mock_reddit(target: str) -> dict:
    return {
        "source": "reddit",
        "kind": "user",
        "target": target.strip().lstrip("/").lstrip("u/").lstrip("r/"),
        "recent_posts": [
            {
                "title": "Mock reddit post",
                "snippet": "This is a mock reddit post body for testing.",
                "subreddit": "r/mock",
                "score": 42,
                "created": "2026-06-30T00:00:00+00:00",
                "url": "https://www.reddit.com/r/mock/comments/mock1",
            }
        ],
    }


# ──────────────────────────── YouTube reader ────────────────────────────────


def _extract_youtube_sync(target: str, max_items: int) -> dict:
    """Blocking yt-dlp metadata extraction. Runs in a threadpool.

    Handle forms accepted: a full YouTube URL, ``@handle``, or a bare handle.
    Only metadata is fetched (``extract_flat`` for playlists; no download).
    """
    import yt_dlp  # imported lazily so the module loads without yt-dlp installed

    query = _safe_youtube_query(target)
    if not query:
        return {}

    # ``playlist_items`` bounds pagination properly for channel tabs; a plain
    # ``playlistend`` does NOT — yt-dlp will crawl every page of the channel's
    # video tab (50+ API round-trips) before honoring the limit. The "1:N" range
    # stops fetching after the requested window.
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "playlist_items": f"1:{max_items}",
        "socket_timeout": 10,
        # Defense-in-depth: never allow the generic HTTP extractor to run, so an
        # unrecognized URL can't be fetched even if it slipped past the host
        # allowlist. Only YouTube extractors are permitted.
        "allowed_extractors": ["youtube", "youtube:tab"],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(query, download=False)

    if not isinstance(info, dict):
        return {}

    entries = info.get("entries") or []
    recent_videos: list[dict] = []
    for e in entries[:max_items]:
        if not isinstance(e, dict):
            continue
        title = e.get("title")
        if not title:
            continue
        ts = e.get("timestamp") or e.get("release_timestamp")
        published: str | None = None
        if isinstance(ts, (int, float)):
            published = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        elif e.get("upload_date"):
            raw = str(e["upload_date"])
            if len(raw) == 8:
                published = f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
        vid_id = e.get("id")
        recent_videos.append({
            "title": str(title)[:300],
            "published": published,
            "url": f"https://youtu.be/{vid_id}" if vid_id else None,
        })

    description = info.get("description")
    return {
        "source": "youtube",
        "channel_title": info.get("channel") or info.get("uploader") or info.get("title"),
        "description": (str(description)[:500] if description else None),
        "url": info.get("channel_url") or info.get("webpage_url"),
        "recent_videos": recent_videos,
    }


async def fetch_youtube(channel_or_video_url: str) -> dict:
    """Read public YouTube channel/video metadata via yt-dlp (metadata only).

    Returns ``{source, channel_title, description, url, recent_videos:[...]}`` or
    ``{}`` on empty input / rate-limit / any error. Never raises. Cached 7 days
    (positive + negative). Honors ``settings.mock_external_apis``.
    """
    target = (channel_or_video_url or "").strip()
    if not target:
        return {}

    if settings.mock_external_apis:
        return _mock_youtube(target)

    cache_key = f"content:yt:{_hash(target)}"
    hit, cached = await _cache_get(cache_key)
    if hit:
        logger.debug("content_youtube_cache_hit", match=cached is not None)
        return cached or {}

    if not await _rate_ok("youtube"):
        logger.warning("content_youtube_rate_limited")
        await _cache_set(cache_key, None, ttl=300)  # brief skip — avoid per-visitor retry storm
        return {}

    max_items = max(1, settings.content_reader_max_items)
    try:
        data = await asyncio.to_thread(_extract_youtube_sync, target, max_items)
    except Exception as exc:
        # yt-dlp raises for private/removed/blocked channels — non-fatal.
        logger.warning("content_youtube_failed", error=str(exc)[:200])
        await _cache_set(cache_key, None)
        return {}

    if not data or not (data.get("recent_videos") or data.get("channel_title")):
        await _cache_set(cache_key, None)
        return {}

    await _cache_set(cache_key, data)
    logger.info("content_youtube_ok", videos=len(data.get("recent_videos") or []))
    return data


# ──────────────────────────── Reddit reader ─────────────────────────────────


def _normalize_reddit_target(username_or_subreddit: str) -> tuple[str, str]:
    """Return (kind, path) where kind is 'user' or 'subreddit'.

    ``r/foo`` / ``/r/foo`` → subreddit; ``u/foo`` / ``@foo`` / bare → user.
    """
    t = username_or_subreddit.strip().lstrip("/")
    low = t.lower()
    if low.startswith("r/"):
        return "subreddit", t[2:].strip("/")
    if low.startswith("u/"):
        return "user", t[2:].strip("/")
    return "user", t.lstrip("@").strip("/")


def _parse_reddit_children(children: list, max_items: int) -> list[dict]:
    posts: list[dict] = []
    for child in children[: max_items * 2]:  # over-scan; filter comments below
        if not isinstance(child, dict):
            continue
        d = child.get("data") or {}
        if not isinstance(d, dict):
            continue
        # Posts (t3) carry a title; comments (t1) carry only body — take posts,
        # fall back to comments if that's all a user profile has.
        title = d.get("title")
        body = d.get("selftext") or d.get("body") or ""
        if not title and not body:
            continue
        created = d.get("created_utc")
        created_iso: str | None = None
        if isinstance(created, (int, float)):
            created_iso = datetime.fromtimestamp(created, tz=timezone.utc).isoformat()
        subreddit = d.get("subreddit")
        permalink = d.get("permalink")
        posts.append({
            "title": (str(title)[:300] if title else None),
            "snippet": str(body)[:300],
            "subreddit": (f"r/{subreddit}" if subreddit else None),
            "score": d.get("score"),
            "created": created_iso,
            "url": (f"https://www.reddit.com{permalink}" if permalink else None),
        })
        if len(posts) >= max_items:
            break
    return posts


async def fetch_reddit(username_or_subreddit: str) -> dict:
    """Read a public Reddit user's recent posts or a subreddit's recent posts.

    Uses reddit.com's public ``.json`` endpoints (no auth). Returns
    ``{source, kind, target, recent_posts:[...]}`` or ``{}`` on empty input /
    rate-limit / 429 / 403 / any error. Never raises. Cached 7 days (positive +
    negative). Honors ``settings.mock_external_apis``.
    """
    raw = (username_or_subreddit or "").strip()
    if not raw:
        return {}

    if settings.mock_external_apis:
        return _mock_reddit(raw)

    kind, name = _normalize_reddit_target(raw)
    if not name:
        return {}

    cache_key = f"content:rd:{_hash(f'{kind}:{name}')}"
    hit, cached = await _cache_get(cache_key)
    if hit:
        logger.debug("content_reddit_cache_hit", match=cached is not None)
        return cached or {}

    if not await _rate_ok("reddit"):
        logger.warning("content_reddit_rate_limited")
        await _cache_set(cache_key, None, ttl=300)  # brief skip — avoid per-visitor retry storm
        return {}

    max_items = max(1, settings.content_reader_max_items)
    if kind == "subreddit":
        url = f"https://www.reddit.com/r/{name}/.json"
    else:
        url = f"https://www.reddit.com/user/{name}/.json"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": _REDDIT_USER_AGENT},
                params={"limit": max_items * 2},
            )
    except httpx.HTTPError as exc:
        logger.warning("content_reddit_http_error", error=str(exc)[:200])
        return {}  # transient network error — don't negative-cache

    if resp.status_code in (403, 429):
        # Throttled/blocked — non-fatal, do NOT negative-cache (try again later).
        logger.warning("content_reddit_throttled", status=resp.status_code)
        return {}
    if resp.status_code == 404:
        logger.debug("content_reddit_not_found", kind=kind)
        await _cache_set(cache_key, None)
        return {}
    if resp.status_code != 200:
        logger.warning("content_reddit_error", status=resp.status_code)
        return {}

    try:
        children = (resp.json().get("data") or {}).get("children") or []
    except (ValueError, AttributeError):
        return {}

    posts = _parse_reddit_children(children, max_items)
    if not posts:
        await _cache_set(cache_key, None)
        return {}

    data = {"source": "reddit", "kind": kind, "target": name, "recent_posts": posts}
    await _cache_set(cache_key, data)
    logger.info("content_reddit_ok", kind=kind, posts=len(posts))
    return data


# ──────────────────────── Handle extraction (P2 support) ────────────────────

_YT_SITE_TOKENS = ("youtube",)
_RD_SITE_TOKENS = ("reddit",)


def _handle_from_url(url: str, host_tokens: tuple[str, ...]) -> str | None:
    """Pull a channel/username out of a profile URL if its host matches."""
    if not url:
        return None
    low = url.lower()
    if not any(tok in low for tok in host_tokens):
        return None
    # Strip protocol + query/fragment, take the meaningful path segment.
    tail = re.sub(r"^https?://", "", url).split("?")[0].split("#")[0]
    parts = [p for p in tail.split("/") if p]
    if len(parts) < 2:
        return None
    # e.g. reddit.com/user/spez → spez; youtube.com/@mkbhd → @mkbhd;
    # youtube.com/channel/UC... → UC...; reddit.com/r/python → r/python
    seg = parts[1]
    if seg in ("user", "u", "channel", "c", "r") and len(parts) >= 3:
        prefix = "r/" if seg == "r" else ""
        return f"{prefix}{parts[2]}"
    return seg


def extract_content_handles(pdl_data: dict | None, social_context: dict | None) -> dict[str, str]:
    """Collect known YouTube / Reddit handles from PDL data + OSINT results.

    Beam rarely has these handles; this returns only what is already known
    (never guesses). Returns e.g. ``{"youtube": "@mkbhd", "reddit": "spez"}`` —
    empty when nothing is found.
    """
    handles: dict[str, str] = {}

    pdl_data = pdl_data or {}
    for key in ("youtube_url", "youtube_handle"):
        if (v := pdl_data.get(key)) and "youtube" not in handles:
            h = _handle_from_url(v, _YT_SITE_TOKENS) if "/" in str(v) else str(v)
            if h:
                handles["youtube"] = h
    for key in ("reddit_url", "reddit_handle"):
        if (v := pdl_data.get(key)) and "reddit" not in handles:
            h = _handle_from_url(v, _RD_SITE_TOKENS) if "/" in str(v) else str(v)
            if h:
                handles["reddit"] = h

    # OSINT / social-resolution accounts stored on social_context.
    if isinstance(social_context, dict):
        accounts: list = []
        for sub_key in ("osint_scan", "social_resolution"):
            sub = social_context.get(sub_key)
            if isinstance(sub, dict):
                accounts += sub.get("accounts") or []
                accounts += sub.get("profiles") or []
        for acc in accounts:
            if not isinstance(acc, dict):
                continue
            site = (acc.get("site_name") or acc.get("platform") or "").lower()
            url = acc.get("url")
            uname = (acc.get("extra") or {}).get("username") or acc.get("handle")
            if "youtube" in site and "youtube" not in handles:
                h = uname or (_handle_from_url(url, _YT_SITE_TOKENS) if url else None)
                if h:
                    handles["youtube"] = h
            elif "reddit" in site and "reddit" not in handles:
                h = uname or (_handle_from_url(url, _RD_SITE_TOKENS) if url else None)
                if h:
                    handles["reddit"] = h

    return handles


async def fetch_content_for_handles(handles: dict[str, str]) -> dict:
    """Fetch YouTube + Reddit content for the given handles.

    Returns a dict suitable for merging into ``social_context`` — e.g.
    ``{"youtube": {...}, "reddit": {...}}``. Missing/failed sources are omitted.
    Non-fatal: any error yields an empty (or partial) dict.
    """
    out: dict = {}
    yt_handle = handles.get("youtube")
    rd_handle = handles.get("reddit")

    if yt_handle:
        try:
            yt = await fetch_youtube(yt_handle)
            if yt:
                out["youtube"] = yt
        except Exception as exc:  # defensive — fetch_* already swallows, belt & braces
            logger.warning("content_youtube_fetch_wrapper_failed", error=str(exc)[:120])
    if rd_handle:
        try:
            rd = await fetch_reddit(rd_handle)
            if rd:
                out["reddit"] = rd
        except Exception as exc:
            logger.warning("content_reddit_fetch_wrapper_failed", error=str(exc)[:120])

    return out


# ──────────────────── recent_content summary (P3 support) ───────────────────

# Cap the personalization string so it can't blow up the campaign prompt or leak
# a firehose of scraped text into the LLM context.
RECENT_CONTENT_MAX_CHARS = 800


def build_recent_content(social_context: dict | None) -> str:
    """Condense ``social_context`` into a short, human-readable personalization
    string for the campaign prompt.

    Pulls from youtube / reddit (P2), twitter recent_posts (social_intelligence),
    and deep_research (enricher). Returns "" when there is nothing usable so the
    prompt stays unchanged for visitors without social context.
    """
    if not isinstance(social_context, dict) or not social_context:
        return ""

    lines: list[str] = []

    def _youtube_line(yt: dict, label: str) -> None:
        titles = [
            v.get("title") for v in (yt.get("recent_videos") or [])
            if isinstance(v, dict) and v.get("title")
        ]
        if titles:
            lines.append(f"{label}: " + "; ".join(titles[:3]))

    def _reddit_line(rd: dict, label: str) -> None:
        titles = [
            p.get("title") or (p.get("snippet") or "")[:80]
            for p in (rd.get("recent_posts") or [])
            if isinstance(p, dict) and (p.get("title") or p.get("snippet"))
        ]
        if titles:
            lines.append(f"{label}: " + "; ".join(t for t in titles[:3] if t))

    yt = social_context.get("youtube")
    if isinstance(yt, dict):
        _youtube_line(yt, "Recent YouTube videos")

    rd = social_context.get("reddit")
    if isinstance(rd, dict):
        _reddit_line(rd, "Recent Reddit posts")

    # P4: company-level content (fallback when no personal handle was known).
    company = social_context.get("company_content")
    if isinstance(company, dict):
        c_yt = company.get("youtube")
        if isinstance(c_yt, dict):
            _youtube_line(c_yt, "Company recent YouTube videos")
        c_rd = company.get("reddit")
        if isinstance(c_rd, dict):
            _reddit_line(c_rd, "Company subreddit posts")

    # Twitter/X recent posts (from social_intelligence.fetch_social_context).
    posts = social_context.get("recent_posts")
    if isinstance(posts, list):
        tweets = [
            (p.get("content") or "")[:120]
            for p in posts
            if isinstance(p, dict) and p.get("content")
        ]
        if tweets:
            lines.append("Recent posts: " + "; ".join(t for t in tweets[:2] if t))

    dr = social_context.get("deep_research")
    if isinstance(dr, str) and dr.strip():
        lines.append("Research summary: " + dr.strip()[:300])

    if not lines:
        return ""

    # Strip angle brackets so scraped visitor text can't forge the
    # <untrusted_visitor_data> fence (prompt-injection / delimiter breakout).
    # sanitize_profiles() also caps/cleans this field, but neutralize here too
    # so it's safe regardless of call ordering.
    text = " | ".join(lines).replace("<", " ").replace(">", " ")
    return text[:RECENT_CONTENT_MAX_CHARS]


# ──────────────────── Company channel discovery (P4) ────────────────────────

# Common free-mail / social hosts that are NOT a company's own domain — never
# treat a match against these as a domain-confidence signal.
_GENERIC_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com",
    "protonmail.com", "aol.com", "youtube.com", "reddit.com", "twitter.com",
    "x.com", "facebook.com", "linkedin.com", "instagram.com",
}


# Common second-level public suffixes so ``acme.co.uk`` → ``acme`` (not ``co``).
# Not a full PSL — just the handful that show up in B2B domains.
_SECOND_LEVEL_TLDS = {
    "co.uk", "org.uk", "gov.uk", "ac.uk", "com.au", "net.au", "org.au",
    "co.nz", "co.jp", "co.in", "com.br", "com.mx", "co.za", "com.sg",
}


def _domain_root(domain: str) -> str:
    """Return the registrable-ish root of a domain (best-effort, no full PSL).

    ``www.acme.co.uk`` → ``acme``; ``blog.acme.com`` → ``acme``. Handles the
    common two-part public suffixes in ``_SECOND_LEVEL_TLDS``; exotic suffixes
    fall back to the second-to-last label (safe: a wrong root just fails the
    confidence gate rather than producing a false match).
    """
    d = (domain or "").strip().lower()
    d = re.sub(r"^https?://", "", d).split("/")[0]
    d = d.split(":")[0]
    if d.startswith("www."):
        d = d[4:]
    parts = d.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in _SECOND_LEVEL_TLDS:
        return parts[-3]
    if len(parts) >= 2:
        return parts[-2]
    return parts[0] if parts else ""


def _domain_matches_url(domain: str, url: str) -> bool:
    """True when ``url`` plausibly belongs to ``domain`` (root token appears)."""
    root = _domain_root(domain)
    if not root or len(root) < 3:
        return False
    return root in (url or "").lower()


async def _find_company_subreddit(company_name: str, domain: str, max_items: int) -> dict | None:
    """Search reddit for a subreddit matching the company; confidence-gated.

    Only returns a result when the company's domain root appears in the
    subreddit name/description/url — avoids matching a generic-name subreddit.
    """
    query = company_name.strip()
    if not query:
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://www.reddit.com/search.json",
                headers={"User-Agent": _REDDIT_USER_AGENT},
                params={"q": query, "type": "sr", "limit": 5},
            )
    except httpx.HTTPError as exc:
        logger.warning("company_subreddit_http_error", error=str(exc)[:120])
        return None
    if resp.status_code != 200:
        logger.debug("company_subreddit_search_status", status=resp.status_code)
        return None
    try:
        children = (resp.json().get("data") or {}).get("children") or []
    except (ValueError, AttributeError):
        return None

    root = _domain_root(domain)
    for child in children:
        d = (child.get("data") or {}) if isinstance(child, dict) else {}
        name = d.get("display_name") or ""
        haystack = " ".join(str(x) for x in (
            name, d.get("title"), d.get("public_description"), d.get("url"),
        )).lower()
        # Confidence gate: the domain root must appear (unless it's generic).
        if root and len(root) >= 3 and root in haystack:
            return {"subreddit": f"r/{name}", "matched_on": "domain_root"}
    return None


async def _find_company_youtube(company_name: str, domain: str) -> dict | None:
    """Use Gemini grounding (reused from enricher.deep_research) to locate a
    company's official YouTube channel URL; confidence-gated on domain.

    Returns ``{"youtube_url": ...}`` only when a plausible official channel is
    found. Key-gated (no Gemini key → None). Non-fatal.
    """
    if not settings.gemini_api_key:
        return None
    from apps.api.services.gemini_client import GeminiError, gemini_generate

    prompt = (
        f"Find the OFFICIAL YouTube channel for the company \"{company_name}\""
        f" (website domain: {domain}). Return ONLY the channel URL on a single "
        f"line (e.g. https://www.youtube.com/@handle). If you are not confident "
        f"it is the official company channel, return the single word NONE. Do "
        f"not guess or invent a channel."
    )
    try:
        text = await gemini_generate(prompt, grounding=True, max_output_tokens=256)
    except GeminiError as exc:
        logger.warning("company_youtube_gemini_error", error=str(exc)[:120])
        return None

    text = (text or "").strip()
    match = re.search(r"https?://(?:www\.)?(?:youtube\.com|youtu\.be)/\S+", text)
    if not match:
        return None
    url = match.group(0).rstrip(".,);")
    return {"youtube_url": url}


async def find_company_channels(company_name: str, domain: str) -> dict:
    """Locate a company's subreddit / YouTube channel by name + domain.

    Confidence-gated (requires a real, non-generic company domain and a
    domain-root match for Reddit). Cached by domain for 30 days (company
    channels are stable). Non-fatal — returns ``{}`` on any miss/error.

    Returns e.g. ``{"reddit": "r/acme", "youtube": "@acme"}`` (handles ready to
    pass to fetch_reddit / fetch_youtube).
    """
    company_name = (company_name or "").strip()
    domain = (domain or "").strip().lower()
    if not company_name or not domain:
        return {}

    root = _domain_root(domain)
    # Generic / free-mail / social domains give no company-confidence signal.
    if domain in _GENERIC_DOMAINS or not root or len(root) < 3:
        logger.debug("company_channels_skipped_generic_domain")
        return {}

    if settings.mock_external_apis:
        return {"reddit": f"r/{root}", "youtube": f"@{root}"}

    cache_key = f"content:company:{_hash(domain)}"
    hit, cached = await _cache_get(cache_key)
    if hit:
        logger.debug("company_channels_cache_hit", match=cached is not None)
        return cached or {}

    if not await _rate_ok("company"):
        logger.warning("company_channels_rate_limited")
        await _cache_set(cache_key, None, ttl=300)  # brief skip — avoid company retry storm
        return {}

    max_items = max(1, settings.content_reader_max_items)
    result: dict = {}

    sub = await _find_company_subreddit(company_name, domain, max_items)
    if sub:
        result["reddit"] = sub["subreddit"]

    yt = await _find_company_youtube(company_name, domain)
    if yt and _domain_matches_url(domain, yt["youtube_url"]):
        # High-confidence only: the domain root must appear in the channel URL.
        result["youtube"] = yt["youtube_url"]
    elif yt:
        logger.debug("company_youtube_rejected_low_confidence")

    # Cache the outcome (positive OR negative) for 30 days.
    await _cache_set(cache_key, result or None, ttl=COMPANY_CHANNEL_CACHE_TTL_SECONDS)
    if result:
        logger.info("company_channels_found", sources=list(result.keys()))
    return result
