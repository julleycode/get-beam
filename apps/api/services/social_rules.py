"""Rule-base social-profile resolver (free, deterministic).

Stage C of the social-resolution pipeline. Given username candidates (derived
from the email local-part, known handles, and the person's name), construct
likely profile URLs from per-platform templates and lightly validate them with a
bounded HTTP probe. Complements Maigret (stage B) for the highest-value sites and
gives the Gemini stage (E) concrete seeds.

Honesty: many sites soft-404 or bot-block, so HTTP validation is noisy. Hits are
labeled `confidence="likely"` only when the username came from a *known* handle
(twitter/github); template guesses are `confidence="guess"`. 403/blocked/unknown
responses are dropped (conservative) rather than reported as found.
"""

from __future__ import annotations

import asyncio
import re
import time

import httpx
import structlog

from apps.api.services.osint_scanner import OsintAccount, _bounded_check

logger = structlog.get_logger()

# platform -> profile URL template ({u} = username). Deterministic, high-value sites.
SITE_URL_TEMPLATES: dict[str, str] = {
    "GitHub": "https://github.com/{u}",
    "GitLab": "https://gitlab.com/{u}",
    "X": "https://x.com/{u}",
    "Instagram": "https://www.instagram.com/{u}/",
    "TikTok": "https://www.tiktok.com/@{u}",
    "YouTube": "https://www.youtube.com/@{u}",
    "Reddit": "https://www.reddit.com/user/{u}",
    "Telegram": "https://t.me/{u}",
    "Medium": "https://medium.com/@{u}",
    "Substack": "https://{u}.substack.com",
    "Twitch": "https://www.twitch.tv/{u}",
    "Pinterest": "https://www.pinterest.com/{u}",
    "Dev.to": "https://dev.to/{u}",
    "Keybase": "https://keybase.io/{u}",
    "Linktree": "https://linktr.ee/{u}",
    "ProductHunt": "https://www.producthunt.com/@{u}",
}

_USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{2,30}$")
# Common non-personal local-parts that make terrible username guesses.
_GENERIC_LOCALS = {
    "info", "admin", "hello", "support", "contact", "team", "sales",
    "hi", "mail", "office", "help", "noreply", "no-reply", "billing",
}


def _norm(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "", s).strip(".-_").lower()


def _slug_from_url(url: str | None) -> str | None:
    if not url:
        return None
    seg = url.rstrip("/").split("/")[-1]
    seg = seg.split("?")[0]
    return seg or None


def derive_username_candidates(
    email: str,
    *,
    twitter_handle: str | None = None,
    github_url: str | None = None,
    full_name: str | None = None,
) -> list[dict]:
    """Return candidate usernames with provenance, highest-signal first.

    Each item: {"username": str, "known": bool}. `known=True` means it came from a
    real handle (twitter/github) → downstream uses higher confidence.
    """
    seen: set[str] = set()
    out: list[dict] = []

    def add(raw: str | None, known: bool):
        if not raw:
            return
        u = _norm(raw)
        if not u or u in seen or not _USERNAME_RE.match(u):
            return
        seen.add(u)
        out.append({"username": u, "known": known})

    # Known handles first (highest signal).
    if twitter_handle:
        add(twitter_handle.lstrip("@"), True)
    add(_slug_from_url(github_url), True)

    # Email local-part + simple variants (only if not a generic mailbox).
    local = (email or "").split("@")[0]
    if local and _norm(local) not in _GENERIC_LOCALS:
        add(local, False)
        add(local.replace(".", ""), False)
        add(local.replace(".", "_"), False)
        add(local.replace("_", "."), False)

    # Name-derived (first.last / firstlast).
    if full_name:
        parts = [p for p in re.split(r"\s+", full_name.strip()) if p]
        if len(parts) >= 2:
            f, l = _norm(parts[0]), _norm(parts[-1])
            if f and l:
                add(f + l, False)
                add(f + "." + l, False)
                add(f + "_" + l, False)

    return out[:8]  # cap the fan-out


async def resolve_via_rules(
    candidates: list[dict],
    *,
    semaphore: asyncio.Semaphore,
    per_check_timeout: float,
    deadline: float,
) -> list[OsintAccount]:
    """Construct + validate template URLs for each candidate. Bounded + never raises."""
    if not candidates:
        return []

    async with httpx.AsyncClient(
        timeout=per_check_timeout,
        headers={"User-Agent": "Mozilla/5.0 (compatible; profile-check/1.0)"},
        follow_redirects=True,
    ) as client:

        async def check(platform: str, template: str, cand: dict):
            username = cand["username"]
            url = template.format(u=username)

            async def _probe():
                resp = await client.get(url)
                return resp

            resp = await _bounded_check(semaphore, deadline, per_check_timeout, _probe)
            if resp is None:
                return None
            # Conservative: only a clean 200 counts. 3xx already followed; a final
            # 404/403/410/blocked → treat as not-found (drop).
            if resp.status_code != 200:
                return None
            # Soft-404 heuristic: if the final URL bounced to a login/home page,
            # the username slug usually drops out of the path.
            final = str(resp.url).rstrip("/")
            if username.lower() not in final.lower():
                return None
            return OsintAccount(
                site_name=platform,
                category="social",
                url=url,
                kind="profile",
                confidence="likely" if cand["known"] else "guess",
                source_engine="rule-base",
                extra={"username": username},
            )

        tasks = [
            check(platform, template, cand)
            for platform, template in SITE_URL_TEMPLATES.items()
            for cand in candidates
        ]
        gathered = await asyncio.gather(*tasks, return_exceptions=True)

    accounts = [a for a in gathered if isinstance(a, OsintAccount)]
    logger.info("rule_base_resolve_done", candidates=len(candidates), hits=len(accounts))
    return accounts
