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
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse

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


# Sources that are keyed by the EMAIL (so the handle belongs to THIS person):
# PDL enrich, OSINT Industries, and user-scanner's email-scan (extra.username).
_EMAIL_KEYED = {"user-scanner", "pdl", "osint-industries"}


def _registered_sites(osint_blob: dict) -> set[str]:
    """Canon, lowercased site names where the EMAIL is registered (right person)."""
    sites: set[str] = set()
    for a in osint_blob.get("accounts", []):
        if a.get("kind") == "registered" and a.get("site_name"):
            sites.add(_canon_site(a["site_name"]).lower())
    return sites


def _url_handle_matches(acc: OsintAccount) -> bool:
    """False when a row claims a handle that its own url does not point at.

    Compares the url's handle POSITION — last path segment, or the leading
    subdomain label for ``https://<handle>.substack.com`` — never a substring:
    "nhanto" is a substring of ".../nhantochi95", which is the exact
    two-different-people pair this whole change exists to separate. Substring
    matching also lets a handle equal to the site's own domain match any url.
    """
    username = ((acc.extra or {}).get("username") or "").strip().lower()
    if not username:
        return True  # no handle claimed → nothing for the url to contradict
    parsed = urlparse(acc.url or "")
    if parsed.path.rstrip("/").rsplit("/", 1)[-1].lstrip("@").lower() == username:
        return True
    return parsed.netloc.split(":")[0].lower().split(".")[0] == username


def _classify(
    acc: OsintAccount,
    full_name: str | None,
    registered_sites: set[str],
    per_site: Counter[str],
) -> str:
    """Identity-based confidence — does this profile belong to the TARGET person?

    confirmed = email-keyed source OR the profile's real name matches full_name.
    likely    = username from a known handle, OR the email is registered on the
                site AND that site narrows to a single candidate.
    guess     = a guessed username, unverified, on a site we can't tie to them.
    """
    extra = acc.extra or {}
    engines = {e.strip() for e in (acc.source_engine or "").split(",") if e.strip()}
    # Email-keyed engines looked the handle up BY the email, so it provably
    # belongs to this person. Most of them return the site homepage as the url
    # (user-scanner does for 102 of its modules), so a url that does not carry
    # the handle means "no profile url available", not "wrong person".
    if engines & _EMAIL_KEYED:
        return "confirmed"
    pname = extra.get("name") or extra.get("fullname") or extra.get("full_name")
    if pname and name_matches(pname, full_name):
        return "confirmed"
    # Below the identity-proven tiers, a handle that its own url does not point
    # at is evidence about nobody: a homepage, a search page, or another site.
    # Demote rather than drop, so numeric-id urls fall to guesses (hidden)
    # instead of vanishing.
    if not _url_handle_matches(acc):
        return "guess"
    if extra.get("cand_source") == "known":
        return "likely"
    # Site-overlap ("the email is registered here") only narrows to a person
    # when the site has exactly ONE candidate. With several candidates it says
    # they use the site but not which of the handles is theirs.
    site = _canon_site(acc.site_name).lower()
    if site in registered_sites and per_site.get(site, 0) == 1:
        return "likely"
    return "guess"


def _verify_identity(
    accounts: list[OsintAccount], full_name: str | None, registered_sites: set[str]
) -> None:
    # A row whose url does not point at its own handle is already ruled out, so
    # it is not a rival candidate — counting it would block the single-candidate
    # rule from ever promoting the one genuine handle on that site.
    eligible = [a for a in accounts if _url_handle_matches(a)]
    per_site: Counter[str] = Counter(
        _canon_site(a.site_name).lower() for a in eligible
    )
    for a in accounts:
        a.confidence = _classify(a, full_name, registered_sites, per_site)
    if len(eligible) != len(accounts):  # counts only — a handle is PII
        logger.info(
            "social_url_handle_mismatch",
            mismatched=len(accounts) - len(eligible), total=len(accounts),
        )


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
    # by_username: these rows came from looking up SEVERAL usernames, so two
    # rows on one site can be two different people. Collapsing by site alone
    # would keep one person's URL beside another person's username.
    unified = _dedupe(profile_accounts, by_username=True)
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
            unified = _dedupe(unified + paid_accounts, by_username=True)
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
