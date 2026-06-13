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
import time
from datetime import datetime, timezone

import structlog

from apps.api.config import settings
from apps.api.services import maigret_engine, paid_osint
from apps.api.services.enricher import Enricher
from apps.api.services.osint_scanner import OsintAccount, _dedupe, run_osint_scan
from apps.api.services.social_rules import derive_username_candidates, resolve_via_rules
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


def _boost_agreement(accounts: list[OsintAccount]) -> None:
    """Profiles confirmed by ≥2 distinct engines → confidence='confirmed'."""
    for a in accounts:
        engines = {e for e in (a.source_engine or "").split(",") if e}
        if len(engines) >= 2:
            a.confidence = "confirmed"


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

    # Unified profile set = OSINT profile-kind hits + Maigret + rule-base.
    profile_accounts = [a for a in osint_accounts if a.kind == "profile"] + resolved_accounts
    for a in profile_accounts:  # canonicalize so cross-engine hits merge
        a.site_name = _canon_site(a.site_name)
    unified = _dedupe(profile_accounts)
    free_profile_count = len(unified)

    # ── Stage F: paid fallback (AUTO, guarded) ──
    paid_info = {"used": False, "provider": "osint-industries", "found": 0,
                 "cached": False, "error": None}
    if (
        free_profile_count < settings.osint_paid_min_profiles
        and paid_osint.is_configured()
    ):
        if await osint_paid_budget_left(visitor.site_id):
            pr = await paid_osint.lookup(email)
            if pr.get("used"):
                await increment_osint_paid_usage(visitor.site_id)
            paid_accounts = [a for a in (_acc(d) for d in pr.get("accounts", [])) if a]
            for a in paid_accounts:
                a.site_name = _canon_site(a.site_name)
            unified = _dedupe(unified + paid_accounts)
            paid_info = {
                "used": bool(pr.get("used")), "provider": "osint-industries",
                "found": pr.get("found", 0), "cached": bool(pr.get("cached")),
                "error": pr.get("error"),
            }
            stages.append("paid")
        else:
            paid_info["error"] = "daily paid budget reached"

    # Profiles agreed on by ≥2 distinct engines are upgraded to "confirmed".
    _boost_agreement(unified)

    # ── Build + persist social_resolution (preserve osint_scan + deep_research) ──
    blob = {
        "status": "complete",
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "stages_run": stages,
        "profiles": [a.to_dict() for a in unified],
        "paid": paid_info,
        "summary": {
            "profile_count": len(unified),
            "free_profile_count": free_profile_count,
            "candidates_used": [c["username"] for c in candidates],
        },
        "message": (
            f"Resolved {len(unified)} social profile(s)."
            + (" Paid lookup used." if paid_info["used"] else "")
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
        "resolve_social_done", email_prefix=email[:5], profiles=len(unified),
        paid_used=paid_info["used"], stages=stages,
    )
    return {
        "status": "complete", "profiles": len(unified),
        "paid_used": paid_info["used"], "stages": stages, "message": blob["message"],
    }
