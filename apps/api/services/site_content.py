"""Fetch + text-extract a customer's site for the onboarding analysis.

Deliberately small and single-posture: DNS-pinned client, no redirects followed
automatically (``safe_get`` re-validates each hop), no cache. It is the ONE choke
point for the analysis path's outbound fetch — ``site_analysis.py`` must never
construct a bare ``httpx.AsyncClient``.

Why not reuse ``content_reader.py``: that module also does fetch + extract, but
for a different purpose and with a different guard posture (yt-dlp / Reddit /
transcript coupling and its own Redis cache semantics). The duplication here is
intentional, not an oversight.

Why not reuse ``platform_detector``'s fetch: that module uses a BARE
``httpx.AsyncClient``, so it has the pre-check and per-hop revalidation but NOT
the DNS-rebinding TOCTOU close. This module follows ``pixel_verifier.py`` instead.
``BROWSER_HEADERS`` is imported from ``platform_detector`` READ-ONLY — that module
must not be edited (an import does not modify it).

Never raises: every failure path returns ``ok=False``.
"""

import re
from typing import TypedDict

import httpx
import structlog

from apps.api.config import settings
from apps.api.services.platform_detector import BROWSER_HEADERS
from apps.api.services.url_guard import is_safe_public_url, pinned_client, safe_get

logger = structlog.get_logger()

# Post-hoc truncation cap on the extracted text handed to the prompt.
MAX_TEXT_CHARS = 12_000
# Content-Length pre-check ceiling. See the note in fetch_site_content about what
# this can and cannot deliver.
MAX_BODY_BYTES = 512 * 1024

_SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.IGNORECASE | re.DOTALL)
_STYLE_RE = re.compile(r"<style\b[^>]*>.*?</style\s*>", re.IGNORECASE | re.DOTALL)
_NOSCRIPT_RE = re.compile(r"<noscript\b[^>]*>.*?</noscript\s*>", re.IGNORECASE | re.DOTALL)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title\s*>", re.IGNORECASE | re.DOTALL)
_META_DESC_RE = re.compile(
    r"""<meta\b[^>]*name\s*=\s*["']description["'][^>]*>""", re.IGNORECASE
)
_CONTENT_ATTR_RE = re.compile(r"""content\s*=\s*["'](.*?)["']""", re.IGNORECASE | re.DOTALL)

_ENTITIES = {
    "&nbsp;": " ",
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&#39;": "'",
    "&apos;": "'",
}


class SiteContent(TypedDict):
    ok: bool
    html: str
    headers: dict[str, str]
    status_code: int | None
    title: str | None
    meta_description: str | None
    text: str


def _empty(ok: bool = False) -> SiteContent:
    return SiteContent(
        ok=ok,
        html="",
        headers={},
        status_code=None,
        title=None,
        meta_description=None,
        text="",
    )


def _unescape(value: str) -> str:
    for entity, char in _ENTITIES.items():
        value = value.replace(entity, char)
    return value


def extract_title(html: str) -> str | None:
    match = _TITLE_RE.search(html)
    if not match:
        return None
    title = _WS_RE.sub(" ", _unescape(_TAG_RE.sub(" ", match.group(1)))).strip()
    return title[:300] or None


def extract_meta_description(html: str) -> str | None:
    tag = _META_DESC_RE.search(html)
    if not tag:
        return None
    content = _CONTENT_ATTR_RE.search(tag.group(0))
    if not content:
        return None
    value = _WS_RE.sub(" ", _unescape(content.group(1))).strip()
    return value[:600] or None


def extract_text(html: str, max_chars: int = MAX_TEXT_CHARS) -> str:
    """Pure-stdlib regex extraction — deliberately no new dependency.

    Strips script/style/noscript bodies and HTML comments FIRST (so their
    contents never reach the prompt), then drops remaining tags, unescapes the
    handful of entities that matter, collapses whitespace and truncates.
    """
    stripped = _SCRIPT_RE.sub(" ", html)
    stripped = _STYLE_RE.sub(" ", stripped)
    stripped = _NOSCRIPT_RE.sub(" ", stripped)
    stripped = _COMMENT_RE.sub(" ", stripped)
    stripped = _TAG_RE.sub(" ", stripped)
    stripped = _unescape(stripped)
    # Drop any stray angle brackets left by malformed markup (e.g. "<<<>>>") or
    # re-introduced by entity unescaping. Same rationale as clean_text: they
    # carry no content signal and they are the only characters that could forge
    # the untrusted-data fence downstream.
    stripped = stripped.replace("<", " ").replace(">", " ")
    return _WS_RE.sub(" ", stripped).strip()[:max_chars]


def _mock_content(url: str) -> SiteContent:
    html = (
        "<html><head><title>Mock Site</title>"
        '<meta name="description" content="A deterministic mock site used when '
        'MOCK_EXTERNAL_APIS is on.">'
        "</head><body><h1>Mock Site</h1>"
        "<p>We sell deterministic fixtures to test suites.</p></body></html>"
    )
    return SiteContent(
        ok=True,
        html=html,
        headers={"content-type": "text/html; charset=utf-8"},
        status_code=200,
        title="Mock Site",
        meta_description=(
            "A deterministic mock site used when MOCK_EXTERNAL_APIS is on."
        ),
        text=extract_text(html),
    )


async def fetch_site_content(url: str) -> SiteContent:
    """Fetch ``url`` through the SSRF guard and extract its text. Never raises.

    Body-cap posture (real, not aspirational): ``safe_get`` does
    ``resp = await client.get(url)``, which FULLY BUFFERS the response before it
    returns — there is no streaming hook to abort mid-download. So the achievable
    cap is (a) a Content-Length pre-check refusing anything over MAX_BODY_BYTES,
    and (b) post-hoc truncation of ``resp.text``.
    ACCEPTED RESIDUAL: a chunked response with no Content-Length is still buffered
    in full before we can refuse it. Bounded blast radius: authed endpoint,
    3 runs/day/site, 10 s timeout. Adding a streaming variant to ``url_guard`` is
    deliberately out of scope here.
    """
    # Mock short-circuit FIRST — defence in depth. Even if a caller forgets its
    # own mock branch, no code path below can issue a live outbound request.
    if settings.mock_external_apis:
        return _mock_content(url)

    if not await is_safe_public_url(url):
        logger.warning("site_content_url_blocked", url_host=_host_of(url))
        return _empty()

    try:
        async with pinned_client(
            timeout=float(settings.site_analysis_fetch_timeout_seconds),
            follow_redirects=False,
            headers=BROWSER_HEADERS,
        ) as client:
            resp = await safe_get(client, url)
    except Exception as exc:
        logger.warning("site_content_fetch_failed", error_class=type(exc).__name__)
        return _empty()

    if resp.status_code >= 400:
        logger.info("site_content_bad_status", status_code=resp.status_code)
        return _empty()

    content_type = resp.headers.get("content-type", "")
    if "html" not in content_type.lower():
        logger.info("site_content_not_html")
        return _empty()

    raw_length = resp.headers.get("content-length")
    if raw_length is not None:
        try:
            if int(raw_length) > MAX_BODY_BYTES:
                logger.info("site_content_too_large", content_length=int(raw_length))
                return _empty()
        except ValueError:
            pass

    try:
        html = resp.text
    except Exception as exc:
        logger.warning("site_content_decode_failed", error_class=type(exc).__name__)
        return _empty()

    return SiteContent(
        ok=True,
        html=html,
        headers=dict(resp.headers),
        status_code=resp.status_code,
        title=extract_title(html),
        meta_description=extract_meta_description(html),
        text=extract_text(html),
    )


def _host_of(url: str) -> str:
    """Host only — never log the full user-supplied URL."""
    try:
        return httpx.URL(url).host or ""
    except Exception:
        return ""
