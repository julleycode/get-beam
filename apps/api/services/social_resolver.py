"""Social-resolution pipeline (stages A–F).

Turns an email into a deduped set of real social profiles using a free-first,
paid-last cascade:

  A. OSINT scan (user-scanner + holehe)  → email→site existence + seed usernames
  B. Maigret (if enabled)                → username→profile across 3000+ sites
  C. Rule-base                           → template profile URLs + light validate
  (D. GHunt — Gmail, opt-in — deferred to Phase 11)
  F. OSINT Industries (paid)             → AUTO only when free profiles < threshold
                                           AND key set AND daily paid budget left
  E. Gemini deep research (grounded)     → seeded by A–F, writes narrative

Writes EnrichmentProfile.social_context (read-modify-write): keeps `osint_scan`,
adds `social_resolution`, and deep_research adds its own key — none clobber.
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone

import structlog

from apps.api.config import settings
from apps.api.services import maigret_engine, paid_osint
from apps.api.services.enricher import Enricher
from apps.api.services.osint_scanner import OsintAccount, _dedupe, run_osint_scan
from apps.api.services.usage_logger import log_api_call
from apps.api.services.social_rules import (
    derive_username_candidates,
    name_matches,
    resolve_via_rules,
)
from apps.api.services.usage_limits import (
    increment_osint_paid_usage,
    osint_paid_budget_left,
)

logger = structlog.get_logger()


def _acc(d: dict) -> OsintAccount | None:
    try:
        return OsintAccount(
            site_name=d.get("site_name", "?"),
            category=d.get("category"),
            url=d.get("url"),
            kind=d.get("kind", "registered"),
            confidence=d.get("confidence", "guess"),
            source_engine=d.get("source_engine", "?"),
            extra=d.get("extra") or {},
        )
    except Exception:
        return None


def _enabled_engines() -> set[str]:
    return {e.strip() for e in settings.osint_engines.split(",") if e.strip()}


# Canonicalize platform names so the SAME platform from different engines dedups
# (and thus cross-confirms) — e.g. Maigret "Twitter" vs rule-base "X".
_SITE_ALIASES = {
    "twitter": "X", "twitter/x": "X", "x": "X",
    "github.com": "GitHub", "instagram.com": "Instagram",
}


def _canon_site(name: str | None) -> str:
    if not name:
        return name or ""
    return _SITE_ALIASES.get(name.strip().lower(), name)


# Sites we never attach to a named real person (legal/defamation + privacy risk).
_ADULT_SITES = {
    "onlyfans", "fansly", "xvideos", "xnxx", "pornhub", "xhamster", "redtube",
    "youporn", "manyvids", "chaturbate", "stripchat", "brazzers", "fancentro",
    "clips4sale", "myfreecams", "cam4", "bongacams", "adultwork", "fapello",
}


def _is_adult(site_name: str | None) -> bool:
    return _canon_site(site_name).lower() in _ADULT_SITES


# Identity-grade sources — confirm on their own (email-keyed, low false-positive).
_GOLD_SOURCES = {"pdl", "osint-industries"}
# Free email-probe — strong but noisy; counts as ONE corroborating signal, not auto-confirm.
_EMAIL_PROBE_SOURCES = {"user-scanner", "holehe"}


def _registered_sites(osint_blob: dict) -> set[str]:
    """Canon, lowercased site names where the EMAIL is registered (right person)."""
    sites: set[str] = set()
    for a in osint_blob.get("accounts", []):
        if a.get("kind") == "registered" and a.get("site_name"):
            sites.add(_canon_site(a["site_name"]).lower())
    return sites


def _is_echoed_handle(pname: str | None, username: str | None) -> bool:
    """True when a profile's 'name' is just the username we searched (sinh ra từ
    chính tên/email của target) — circular, NOT independent evidence."""
    if not pname or not username:
        return False
    a = re.sub(r"[^a-z0-9]", "", pname.lower())
    b = re.sub(r"[^a-z0-9]", "", username.lower())
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _classify(acc: OsintAccount, full_name: str | None, registered_sites: set[str]) -> str:
    """Identity confidence via independent corroborating signals.

    Gold sources (PDL enrichment, paid OSINT Industries) confirm alone.
    Otherwise ≥2 independent signals → confirmed, exactly 1 → likely, 0 → guess.
    Signals: (a) site's real display name matches full_name and is NOT just the
    handle we searched; (b) the handle came from a verified real account
    (twitter/github); (c) the target's email is registered on this same site;
    (d) a free email-probe surfaced this handle directly.
    """
    engines = {e.strip() for e in (acc.source_engine or "").split(",") if e.strip()}
    if engines & _GOLD_SOURCES:
        return "confirmed"

    extra = acc.extra or {}
    pname = extra.get("name") or extra.get("fullname") or extra.get("full_name")
    uname = extra.get("username")

    signals = 0
    if pname and not _is_echoed_handle(pname, uname) and name_matches(pname, full_name):
        signals += 1
    if extra.get("cand_source") == "known":
        signals += 1
    if _canon_site(acc.site_name).lower() in registered_sites:
        signals += 1
    if engines & _EMAIL_PROBE_SOURCES:
        signals += 1

    if signals >= 2:
        return "confirmed"
    if signals == 1:
        return "likely"
    return "guess"


def _verify_identity(
    accounts: list[OsintAccount], full_name: str | None, registered_sites: set[str]
) -> None:
    for a in accounts:
        a.confidence = _classify(a, full_name, registered_sites)


def _slug(url: str | None) -> str | None:
    if not url:
        return None
    seg = url.rstrip("/").split("/")[-1].split("?")[0]
    return seg or None


def _pdl_accounts(profile) -> list[OsintAccount]:
    """Email-keyed handles PDL/Proxycurl already wrote to the profile → confirmed."""
    out: list[OsintAccount] = []
    li = getattr(profile, "linkedin_url", None)
    if li:
        out.append(OsintAccount("LinkedIn", "professional", li, "profile",
                                 "confirmed", "pdl", {"username": _slug(li) or ""}))
    tw = getattr(profile, "twitter_handle", None)
    if tw:
        h = tw.lstrip("@")
        out.append(OsintAccount("X", "social", f"https://x.com/{h}", "profile",
                                 "confirmed", "pdl", {"username": h}))
    gh = getattr(profile, "github_url", None)
    if gh:
        out.append(OsintAccount("GitHub", "dev", gh, "profile",
                                 "confirmed", "pdl", {"username": _slug(gh) or ""}))
    return out


async def resolve_social(db, *, visitor, identified, profile, run_gemini: bool = True) -> dict:
    """Run the full pipeline for one visitor. Persists results. Never raises."""
    email = (identified.email if identified else None) or ""
    email = email.strip()
    if not email:
        return {"status": "not_identified", "profiles": 0, "paid_used": False,
                "stages": [], "message": "Visitor has no email to resolve."}

    stages: list[str] = []
    engines = _enabled_engines()

    # ── Stage A0: cascade enrichment (PDL → Proxycurl → Twitter) ──
    # Populates job/company + LinkedIn/Twitter on the profile (the "Enrichment"
    # card) AND gives the handles below higher-signal username candidates.
    try:
        await Enricher(db).enrich_tier1(visitor, identified)
        stages.append("enrich")
    except Exception as e:
        logger.warning("resolve_social_enrich_failed", error=str(e))

    # ── Stage A: free OSINT email→existence (cached/fresh) ──
    osint_blob = await run_osint_scan(email)
    stages.append("osint_free")
    osint_accounts = [a for a in (_acc(d) for d in osint_blob.get("accounts", [])) if a]

    # ── Username candidates (email + known handles + name + OSINT extras) ──
    candidates = derive_username_candidates(
        email,
        twitter_handle=getattr(profile, "twitter_handle", None) if profile else None,
        github_url=getattr(profile, "github_url", None) if profile else None,
        full_name=identified.full_name if identified else None,
    )
    have = {c["username"] for c in candidates}
    for a in osint_accounts:
        u = (a.extra or {}).get("username")
        if u and u.lower() not in {h.lower() for h in have}:
            candidates.append({"username": u, "known": True})
            have.add(u)
    candidates = candidates[:10]

    # ── Stages B (Maigret) + C (rule-base), concurrently, bounded ──
    semaphore = asyncio.Semaphore(max(1, settings.osint_scan_concurrency))
    deadline = time.monotonic() + settings.osint_scan_wall_clock_cap
    tasks = []
    run_maigret = "maigret" in engines and maigret_engine.is_available()
    if run_maigret:
        tasks.append(maigret_engine.search_usernames(
            candidates, top_sites=settings.osint_maigret_top_sites,
            per_username_timeout=settings.osint_scan_per_module_timeout, deadline=deadline,
            parse=settings.osint_maigret_parse,
        ))
        stages.append("maigret")
    tasks.append(resolve_via_rules(
        candidates, semaphore=semaphore,
        per_check_timeout=settings.osint_scan_per_module_timeout, deadline=deadline,
    ))
    stages.append("rule_base")

    gathered = await asyncio.gather(*tasks, return_exceptions=True)
    resolved_accounts: list[OsintAccount] = []
    for r in gathered:
        if isinstance(r, list):
            resolved_accounts.extend(x for x in r if isinstance(x, OsintAccount))

    # Email-keyed signals: PDL handles already on the profile + the set of sites
    # the EMAIL is registered on (used to verify identity / narrow).
    pdl_accounts = _pdl_accounts(profile)
    registered_sites = _registered_sites(osint_blob)
    full_name = identified.full_name if identified else None

    # Unified set = PDL handles + OSINT profile-kind hits + Maigret + rule-base.
    profile_accounts = (
        pdl_accounts
        + [a for a in osint_accounts if a.kind == "profile"]
        + resolved_accounts
    )
    for a in profile_accounts:  # canonicalize so cross-engine hits merge/cross-confirm
        a.site_name = _canon_site(a.site_name)
    unified = _dedupe(profile_accounts)
    _verify_identity(unified, full_name, registered_sites)
    confirmed_count = sum(1 for a in unified if a.confidence == "confirmed")

    # ── Stage F: paid fallback — AUTO only when too few CONFIRMED profiles ──
    paid_info = {"used": False, "provider": "osint-industries", "found": 0,
                 "cached": False, "error": None}
    if (
        confirmed_count < settings.osint_paid_min_profiles
        and paid_osint.is_configured()
    ):
        if await osint_paid_budget_left(visitor.site_id):
            pr = await paid_osint.lookup(email)
            if pr.get("used"):
                await increment_osint_paid_usage(visitor.site_id)
                # Billable OSINT Industries credit ($1) → cost ledger. Own
                # session, best-effort; never breaks resolution.
                await log_api_call(
                    site_id=visitor.site_id,
                    visitor_id=visitor.visitor_id,
                    provider="osint-industries",
                    category="osint",
                    operation="email_lookup",
                    success=not pr.get("error"),
                    units=1,
                )
            paid_accounts = [a for a in (_acc(d) for d in pr.get("accounts", [])) if a]
            for a in paid_accounts:
                a.site_name = _canon_site(a.site_name)
            unified = _dedupe(unified + paid_accounts)
            _verify_identity(unified, full_name, registered_sites)
            confirmed_count = sum(1 for a in unified if a.confidence == "confirmed")
            paid_info = {
                "used": bool(pr.get("used")), "provider": "osint-industries",
                "found": pr.get("found", 0), "cached": bool(pr.get("cached")),
                "error": pr.get("error"),
            }
            stages.append("paid")
        else:
            paid_info["error"] = "daily paid budget reached"

    # ── Drop adult/NSFW sites entirely (legal/defamation + privacy risk) ──
    # Single serialization point: filter the unified set BEFORE the partition so
    # adult accounts never reach `profiles` or `guesses`, and recompute counts so
    # the summary stays internally consistent.
    hidden_adult = sum(1 for a in unified if _is_adult(a.site_name))
    if hidden_adult:
        unified = [a for a in unified if not _is_adult(a.site_name)]
        confirmed_count = sum(1 for a in unified if a.confidence == "confirmed")

    # ── Narrow: keep verified (confirmed + likely); collapse pure guesses ──
    verified = [a for a in unified if a.confidence in ("confirmed", "likely")]
    verified.sort(key=lambda a: 0 if a.confidence == "confirmed" else 1)
    guesses = [a for a in unified if a.confidence == "guess"]
    likely_count = len(verified) - confirmed_count

    # ── Build + persist social_resolution (preserve osint_scan + deep_research) ──
    blob = {
        "status": "complete",
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "stages_run": stages,
        "profiles": [a.to_dict() for a in verified],
        "guesses": [a.to_dict() for a in guesses],
        "paid": paid_info,
        "summary": {
            "profile_count": len(verified),
            "confirmed_count": confirmed_count,
            "likely_count": likely_count,
            "guess_count": len(guesses),
            "hidden_adult": hidden_adult,
            "candidates_used": [c["username"] for c in candidates],
        },
        "message": (
            f"{confirmed_count} verified profile(s), {likely_count} likely"
            + (f", {len(guesses)} unverified guess(es)" if guesses else "")
            + (" · paid lookup used" if paid_info["used"] else "")
        ),
    }
    merged = dict(profile.social_context or {})
    merged["osint_scan"] = osint_blob
    merged["social_resolution"] = blob
    profile.social_context = merged
    await db.commit()

    # ── Stage E: Gemini deep research, seeded by everything above ──
    if run_gemini and settings.gemini_api_key:
        try:
            await Enricher(db).deep_research(
                visitor, identified, profile,
                osint_seed={"osint_scan": osint_blob, "social_resolution": blob},
            )
            stages.append("gemini")
        except Exception as e:  # GeminiError included — never let Gemini break the pipeline
            logger.warning("resolve_social_gemini_failed", error=str(e))

    logger.info(
        "resolve_social_done", email_prefix=email[:5], verified=len(verified),
        confirmed=confirmed_count, guesses=len(guesses),
        paid_used=paid_info["used"], stages=stages,
    )
    return {
        "status": "complete", "profiles": len(verified), "confirmed": confirmed_count,
        "paid_used": paid_info["used"], "stages": stages, "message": blob["message"],
    }
