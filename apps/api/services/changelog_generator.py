"""Changelog auto-generator: merged GitHub PRs → Gemini → published entries.

Pulls recently merged PRs, asks Gemini to (a) decide whether each one is worth
telling customers about and (b) rewrite the dev title/body into one plain,
benefit-led line. Internal work (refactors, chores, tests, pure-backend
hardening) is dropped. Idempotent via `changelog_entries.source_ref = "pr-<n>"`.

This is the "auto-publish from what I ship" path. The Gemini classify step is
the guardrail that stops internal jargon from landing on the public site —
it replaces the manual review step the operator opted out of.
"""

import json
import re
from datetime import datetime, timezone

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.changelog_entry import ChangelogEntry
from apps.api.schemas.changelog import ChangelogSyncResponse
from apps.api.services.gemini_client import GeminiError, gemini_generate

logger = structlog.get_logger(__name__)

_VALID_CATEGORIES = {"new", "improved", "fixed"}
_GITHUB_API = "https://api.github.com"

# The editorial brief Gemini applies to every PR. Kept verbatim-stable so the
# daily job and a manual sync produce the same voice.
_PROMPT = """You turn a software team's merged pull request into a public changelog entry for "Beam", a tool that identifies anonymous website visitors and helps founders reach out to them.

Audience: non-technical founders and marketers using the product. They do NOT care about code structure.

Decide if this PR is worth announcing to customers, then rewrite it.

DROP (worthy=false) if the PR is internal-only: refactors, code cleanup, file splits, renames, tests, CI, dependency bumps, "phase N" structural work, or backend hardening with no user-visible effect.

KEEP (worthy=true) if a customer would notice: a new feature, a visible improvement, or a fix to something they could have hit.

When worthy, write:
- "category": one of "new" (new capability), "improved" (better existing thing), "fixed" (bug fix).
- "title": <= 60 chars, plain language, benefit-led. NO file names, NO "Phase", NO jargon, NO emoji, lowercase-friendly is fine.
- "body": ONE sentence (<= 140 chars) on what it means for the user. Concrete, no fluff words like "seamless" or "elevate".

Return ONLY a JSON object, no markdown fence:
{"worthy": true/false, "category": "...", "title": "...", "body": "..."}

PR title: %(title)s
PR description: %(body)s
"""


class ChangelogSyncError(RuntimeError):
    """Raised when the sync cannot run (e.g. missing GitHub token)."""


async def fetch_recent_merged_prs(limit: int = 30) -> list[dict]:
    """Recently merged PRs (newest merge first). Requires a GitHub token."""
    if not settings.github_token:
        raise ChangelogSyncError("GITHUB_TOKEN is not configured")
    headers = {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url = f"{_GITHUB_API}/repos/{settings.github_repo}/pulls"
    params = {"state": "closed", "sort": "updated", "direction": "desc", "per_page": 100}
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(url, headers=headers, params=params)
    if resp.status_code != 200:
        raise ChangelogSyncError(f"GitHub API {resp.status_code}: {resp.text[:200]}")
    merged = [p for p in resp.json() if p.get("merged_at")]
    merged.sort(key=lambda p: p["merged_at"], reverse=True)
    return merged[:limit]


def _parse_gemini_json(raw: str) -> dict | None:
    """Extract the first JSON object from a Gemini reply (tolerates fences)."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


async def classify_and_rewrite(title: str, body: str) -> dict | None:
    """Ask Gemini to judge + rewrite a PR. Returns a clean entry dict or None.

    None means "skip" — either Gemini judged it internal, or the call/parse
    failed. We never publish on uncertainty (no jargon leaks to the site).
    """
    prompt = _PROMPT % {"title": title, "body": (body or "")[:1500]}
    try:
        raw = await gemini_generate(prompt, max_output_tokens=300)
    except GeminiError as exc:
        logger.warning("changelog_gemini_failed", error=str(exc))
        return None
    data = _parse_gemini_json(raw)
    if not data or not data.get("worthy"):
        return None
    category = str(data.get("category", "new")).lower()
    if category not in _VALID_CATEGORIES:
        category = "new"
    title_out = str(data.get("title", "")).strip()[:255]
    if not title_out:
        return None
    return {
        "category": category,
        "title": title_out,
        "body": str(data.get("body", "")).strip()[:2000],
    }


async def sync_from_github(db: AsyncSession, limit: int = 30) -> ChangelogSyncResponse:
    """Pull recent merged PRs and auto-publish the customer-facing ones.

    Idempotent: a PR already imported (by source_ref) is skipped without a
    Gemini call. New worthy PRs become published entries stamped with their
    merge time so the landing page orders them correctly.
    """
    prs = await fetch_recent_merged_prs(limit=limit)
    refs = [f"pr-{p['number']}" for p in prs]
    existing = set(
        (
            await db.execute(
                select(ChangelogEntry.source_ref).where(
                    ChangelogEntry.source_ref.in_(refs)
                )
            )
        ).scalars().all()
    )

    imported = skipped_internal = already = 0
    for pr in prs:
        ref = f"pr-{pr['number']}"
        if ref in existing:
            already += 1
            continue
        entry = await classify_and_rewrite(pr.get("title", ""), pr.get("body", ""))
        if entry is None:
            skipped_internal += 1
            continue
        merged_at = _parse_iso(pr.get("merged_at"))
        db.add(
            ChangelogEntry(
                title=entry["title"],
                body=entry["body"],
                category=entry["category"],
                status="published",
                published_at=merged_at or datetime.now(timezone.utc),
                source_ref=ref,
            )
        )
        imported += 1

    if imported:
        await db.commit()
    logger.info(
        "changelog_synced",
        scanned=len(prs),
        imported=imported,
        skipped_internal=skipped_internal,
        already_present=already,
    )
    return ChangelogSyncResponse(
        scanned=len(prs),
        imported=imported,
        skipped_internal=skipped_internal,
        already_present=already,
    )


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
