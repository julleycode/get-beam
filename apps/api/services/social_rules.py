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
import unicodedata

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


def _name_tokens(s: str | None) -> list[str]:
    """Lowercased, diacritic-stripped name tokens (Nguyễn → nguyen)."""
    if not s:
        return []
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", s.lower())


def name_matches(profile_name: str | None, full_name: str | None) -> bool:
    """True if a profile's display name plausibly belongs to the target person.

    Requires ≥2 shared name tokens (a single shared token like a common surname
    "nguyen" is far too weak), or a concatenation containment for handle-style
    names with no spaces (e.g. "nathannguyennhat" ⊂ "Nathan Nguyen Nhat").
    """
    pt = _name_tokens(profile_name)
    ft = _name_tokens(full_name)
    if not pt or not ft:
        return False
    if len(set(pt) & set(ft)) >= 2:
        return True
    pc, fc = "".join(pt), "".join(ft)
    if len(pc) >= 6 and len(fc) >= 6 and (pc in fc or fc in pc):
        return True
    return False


def derive_username_candidates(
    email: str,
    *,
    twitter_handle: str | None = None,
    github_url: str | None = None,
    full_name: str | None = None,
) -> list[dict]:
    """Candidate usernames with provenance, highest-signal first.

    Each item: {"username", "known": bool, "source"}. source ∈
    {"known" (real handle), "name" (from full name), "email" (local-part)}.
    NAME-derived candidates come before the email local-part — a person's handle
    rarely matches their email prefix (the root cause of the wrong-person bug).
    """
    seen: set[str] = set()
    out: list[dict] = []

    def add(raw: str | None, source: str):
        if not raw:
            return
        u = _norm(raw)
        if not u or u in seen or not _USERNAME_RE.match(u):
            return
        seen.add(u)
        out.append({"username": u, "known": source == "known", "source": source})

    # 1) Known real handles (highest signal — email-keyed via PDL/enrichment).
    if twitter_handle:
        add(twitter_handle.lstrip("@"), "known")
    add(_slug_from_url(github_url), "known")

    # 2) Name-derived patterns (the realistic source of a personal handle).
    toks = _name_tokens(full_name)
    if len(toks) >= 2:
        f, l = toks[0], toks[-1]
        rest = "".join(toks[1:])  # e.g. "nguyennhat"
        allc = "".join(toks)  # "nathannguyennhat"
        for cand in (
            f + l, l + f, allc,
            f + "." + l, f + "_" + l, f + "-" + l,
            "-".join(toks), ".".join(toks),
            f + rest, f + "-" + rest, f + "." + rest,
            f[0] + l, f + l[0],
        ):
            add(cand, "name")

    # 3) Email local-part (weakest — usually NOT the person's handle).
    local = (email or "").split("@")[0]
    if local and _norm(local) not in _GENERIC_LOCALS:
        add(local, "email")
        add(local.replace(".", ""), "email")

    return out[:12]  # cap the fan-out (verification filters the rest)


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
                # Provisional — the resolver's identity check recomputes this.
                confidence="likely" if cand["known"] else "guess",
                source_engine="rule-base",
                extra={"username": username, "cand_source": cand.get("source", "name")},
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
