"""Rule-base social-profile resolver (free, deterministic).

Stage C of the social-resolution pipeline. Given username candidates (derived
from the email local-part, known handles, and the person's name), construct
likely profile URLs from per-platform templates and lightly validate them with a
bounded HTTP probe. Complements Maigret (stage B) for the highest-value sites and
gives the Gemini stage (E) concrete seeds.

Verification reads the PAGE, not just the status line. A status-only check said
"found" for 6 of 16 sites when probed with a username that cannot exist (measured
11-08-26): plenty of sites answer 200 for a nonexistent user by serving a login
or home page. Each check now requires the site's expected marker string to be
present and its "missing" marker to be absent — the WhatsMyName methodology.
Probed against all 356 B2B sites, that rule produced 0 false positives.

Hits are labeled `confidence="likely"` only when the username came from a *known*
handle (twitter/github); guesses are `confidence="guess"`. Either way the label is
provisional — social_resolver._classify recomputes it.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import unicodedata
from pathlib import Path

import httpx
import structlog

from apps.api.config import settings
from apps.api.services.osint_scanner import (
    OsintAccount,
    _bounded_check,
    is_skipped_category,
)

logger = structlog.get_logger()

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_WMN_DATA = _DATA_DIR / "wmn-data.json"
_WMN_BROAD_LIST = _DATA_DIR / "wmn-broad-sites.json"

# Display platform -> WhatsMyName site name, for the deep tier.
#
# Two different urls per site, deliberately: WhatsMyName's `uri_check` is often
# an API endpoint (api.github.com/users/{account}) and its `e_string` matches
# that API's response, not the html profile page — so the CHECK must use it. The
# url we store is the hand-written template below, because a salesperson has to
# be able to click it. Keys here must exist in SITE_URL_TEMPLATES.
DEEP_TIER_WMN: dict[str, str] = {
    "GitHub": "GitHub (User)",
    "GitLab": "gitlab",
    "X": "X",
    "Instagram": "Instagram",
    "TikTok": "TikTok",
    "YouTube": "YouTube User",
    "Reddit": "Reddit",
    "Telegram": "Telegram",
    "Medium": "Medium",
    "Substack": "Substack",
    "Twitch": "Twitch",
    "Pinterest": "Pinterest",
    "Dev.to": "dev.to",
    "Keybase": "Keybase",
    "Linktree": "Linktree",
    "ProductHunt": "ProductHunt",
}

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


_wmn_raw: list[dict] | None = None


def _load_wmn() -> list[dict]:
    """Parse wmn-data.json once per process (same module-cache shape as
    maigret_engine._load_db). Category filtering is applied per call, not here,
    so a settings change is picked up without a restart."""
    global _wmn_raw
    if _wmn_raw is None:
        try:
            _wmn_raw = json.loads(_WMN_DATA.read_text(encoding="utf-8"))["sites"]
        except Exception as e:  # missing/corrupt data must not break the pipeline
            logger.warning("wmn_data_load_failed", err=str(e))
            _wmn_raw = []
    return _wmn_raw


def _wmn_by_name() -> dict[str, dict]:
    """Usable WhatsMyName entries, keyed by lowercased site name.

    Drops entries with no `e_string` (nothing to verify against) and anything in
    a skipped category. The category test is substring-based: WhatsMyName labels
    its adult sites `xx NSFW xx`, which an equality test against
    {"adult","nsfw","porn"} silently lets through — 39 sites' worth.
    """
    skip = {
        c.strip().lower()
        for c in settings.osint_scan_skip_categories.split(",")
        if c.strip()
    }
    return {
        s["name"].lower(): s
        for s in _load_wmn()
        if s.get("e_string") and s.get("uri_check")
        and not is_skipped_category(s.get("cat"), skip)
    }


_broad_names: list[str] | None = None


def _broad_site_names() -> list[str]:
    """Broad-tier site names, in priority order.

    The order comes from an offline survey (see the `method` field in the file
    and reports/wmn-site-survey.md): every candidate was probed with real
    usernames plus a ghost username, then ranked by measured latency. It is NOT
    wmn-data.json's file order, which carries no ranking of any kind — inventing
    a "top-N by popularity" from that order would be fiction.
    """
    global _broad_names
    if _broad_names is None:
        try:
            _broad_names = json.loads(
                _WMN_BROAD_LIST.read_text(encoding="utf-8")
            )["sites"]
        except Exception as e:
            logger.warning("wmn_broad_list_load_failed", err=str(e))
            _broad_names = []
    return _broad_names


def _plan_checks(candidates: list[dict]) -> list[tuple[str, str, dict, dict]]:
    """(display_name, display_url, wmn_entry, candidate) for every check to run.

    Deep tier first (high-value sites, every candidate), then the broad tier
    (survey-picked sites, best candidate only), truncated to the hard request
    ceiling so a large candidate list can never blow the shared 45s budget.
    """
    entries = _wmn_by_name()
    eligible_cats = {
        c.strip().lower()
        for c in settings.osint_rules_categories.split(",")
        if c.strip()
    }
    planned: list[tuple[str, str, dict, dict]] = []

    for display, wmn_name in DEEP_TIER_WMN.items():
        entry = entries.get(wmn_name.lower())
        if entry is None:
            continue
        for cand in candidates:
            planned.append(
                (display, SITE_URL_TEMPLATES[display].format(u=cand["username"]),
                 entry, cand)
            )

    broad_cands = candidates[: max(0, settings.osint_rules_broad_candidates)]
    broad_budget = max(0, settings.osint_rules_broad_sites)
    for name in _broad_site_names()[:broad_budget]:
        entry = entries.get(name.lower())
        if entry is None or (entry.get("cat") or "").lower() not in eligible_cats:
            continue
        for cand in broad_cands:
            url = entry["uri_check"].replace("{account}", cand["username"])
            planned.append((entry["name"], url, entry, cand))

    cap = max(0, settings.osint_rules_max_requests)
    if len(planned) > cap:
        logger.info("rule_base_budget_truncated", planned=len(planned), cap=cap)
        planned = planned[:cap]
    return planned


def _is_hit(entry: dict, resp) -> bool:
    """WhatsMyName content check: expected marker present, missing marker absent.

    A status code alone is not evidence — probed with a username that cannot
    exist, status-only verification called 6 of 16 sites a hit (11-08-26),
    because they answer 200 with a login or home page.

    The whole body is searched on purpose. Capping the scan at the first 200KB
    was tried and measured wrong: Pinterest (1.6MB) and YouTube (2.4MB) carry
    their marker past that point, so the cap turned real profiles into misses.
    It saved nothing either — httpx has already buffered the full response by
    the time this runs, so the cap bounded substring CPU, never bandwidth.
    """
    if resp.status_code != entry.get("e_code", 200):
        return False
    try:
        text = resp.text
    except Exception:
        return False
    if entry["e_string"] not in text:
        return False
    m_string = entry.get("m_string")
    return not (m_string and m_string in text)


async def resolve_via_rules(
    candidates: list[dict],
    *,
    semaphore: asyncio.Semaphore,
    per_check_timeout: float,
    deadline: float,
) -> list[OsintAccount]:
    """Content-verify candidate handles across two site tiers. Never raises."""
    if not candidates:
        return []
    planned = _plan_checks(candidates)
    if not planned:
        return []

    async with httpx.AsyncClient(
        timeout=per_check_timeout,
        headers={"User-Agent": "Mozilla/5.0 (compatible; profile-check/1.0)"},
        follow_redirects=True,
    ) as client:

        async def check(display: str, display_url: str, entry: dict, cand: dict):
            probe_url = entry["uri_check"].replace("{account}", cand["username"])

            async def _probe():
                return await client.get(probe_url)

            resp = await _bounded_check(semaphore, deadline, per_check_timeout, _probe)
            if resp is None or not _is_hit(entry, resp):
                return None
            return OsintAccount(
                site_name=display,
                category=entry.get("cat") or "social",
                url=display_url,
                kind="profile",
                # Provisional — the resolver's identity check recomputes this.
                confidence="likely" if cand["known"] else "guess",
                source_engine="rule-base",
                extra={"username": cand["username"],
                       "cand_source": cand.get("source", "name")},
            )

        gathered = await asyncio.gather(
            *(check(*p) for p in planned), return_exceptions=True
        )

    accounts = [a for a in gathered if isinstance(a, OsintAccount)]
    logger.info("rule_base_resolve_done", candidates=len(candidates),
                checks=len(planned), hits=len(accounts))
    return accounts
