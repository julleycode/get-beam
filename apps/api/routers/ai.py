"""AI assistant endpoint — the dashboard Overview "ask Beam anything" box.

A single Gemini-backed endpoint that answers questions about the signed-in
user's OWN Beam data (visitor / segment / campaign / draft counts) plus general
Beam product knowledge, and points them at the right dashboard action. Context
is built only from the caller's sites, so one tenant can never read another's
numbers. IP rate-limited to protect the Gemini free-tier quota.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents.prompt_safety import clean_text
from apps.api.dependencies import get_current_user
from apps.api.models.campaign import Campaign
from apps.api.models.database import get_db
from apps.api.models.draft import Draft, DraftStatus
from apps.api.models.segment import Segment
from apps.api.models.site import Site
from apps.api.models.user import User
from apps.api.routers.visitors import _compute_visitor_stat_counts
from apps.api.services.gemini_client import GeminiError, gemini_generate
from apps.api.services.rate_limiter import limiter

logger = structlog.get_logger()

router = APIRouter()


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    site_id: str | None = None


class AskResponse(BaseModel):
    answer: str


_PREAMBLE = (
    "You are Beam's in-app assistant. Beam identifies anonymous website "
    "visitors, enriches their profiles, and helps turn them into outreach via "
    "email and social. Answer the user's question in 1-4 short sentences, "
    "grounded ONLY in the WORKSPACE DATA and PRODUCT RULES below. Be concrete "
    "and name the exact dashboard page or button to use (Visitors, Segments, "
    "Campaigns, Drafts, Feed, Settings). If the data does not contain the "
    "answer, say so plainly. Never invent numbers."
)

_RULES = (
    "PRODUCT RULES: Identity is resolved only for visitors with intent score "
    ">= 40. Segmentation becomes worthwhile once ~10+ enriched visitors "
    "accumulate. Campaign status flows draft -> approved -> active -> "
    "completed; emails send only while a campaign is 'active' (human-approval "
    "gate), capped at 50/hour per site. Social reply drafts sit in 'pending' "
    "until the user approves them."
)


async def _site_line(db: AsyncSession, site: Site) -> str:
    """One compact, safe data line per site for the prompt context."""
    counts = await _compute_visitor_stat_counts(db, site.site_id)
    camp_rows = (
        await db.execute(
            select(Campaign.status, func.count())
            .where(Campaign.site_id == site.site_id)
            .group_by(Campaign.status)
        )
    ).all()
    camp = {status: int(n) for status, n in camp_rows}
    seg_count = (
        await db.execute(
            select(func.count())
            .select_from(Segment)
            .where(Segment.site_id == site.site_id)
        )
    ).scalar() or 0
    return (
        f'- Site "{clean_text(site.name, 80)}" ({clean_text(site.url, 120)}): '
        f"{counts['total']} visitors, {counts['identified']} identified, "
        f"{counts['enriched']} enriched, {counts['eligible_for_resolution']} ready to "
        f"identify (intent>=40), {counts['enriched_unsegmented']} enriched-but-unsegmented, "
        f"{int(seg_count)} segments; campaigns: {camp.get('draft', 0)} draft, "
        f"{camp.get('active', 0)} active, {camp.get('completed', 0)} completed; "
        f"pixel {'installed' if site.pixel_verified else 'NOT installed'}."
    )


async def _build_context(db: AsyncSession, user: User, site: Site | None) -> str:
    """Compact text snapshot of the caller's workspace. Scoped to their sites."""
    if site is not None:
        sites = [site]
    else:
        sites = list(
            (await db.execute(select(Site).where(Site.user_id == user.id)))
            .scalars()
            .all()
        )
    if not sites:
        return (
            "WORKSPACE DATA: the user has no sites yet — first step is to create "
            "a site and install the Beam pixel from the onboarding flow."
        )

    # Drafts are per-user (not per-site) — count once.
    pending_drafts = (
        await db.execute(
            select(func.count())
            .select_from(Draft)
            .where(Draft.user_id == user.id, Draft.status == DraftStatus.pending)
        )
    ).scalar() or 0

    lines = [await _site_line(db, s) for s in sites]
    lines.append(
        f"- Social reply drafts pending approval (all sites): {int(pending_drafts)}."
    )
    return "WORKSPACE DATA:\n" + "\n".join(lines)


@router.post("/ask", response_model=AskResponse)
@limiter.limit("10/minute")
async def ask(
    request: Request,
    body: AskRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AskResponse:
    """Answer a free-text question about the caller's Beam workspace via Gemini."""
    site: Site | None = None
    if body.site_id:
        result = await db.execute(
            select(Site).where(
                Site.site_id == body.site_id, Site.user_id == user.id
            )
        )
        site = result.scalar_one_or_none()
        # 404 (not 403) so we don't leak which site_ids exist.
        if site is None:
            raise HTTPException(status_code=404, detail="Site not found")

    context = await _build_context(db, user, site)
    question = clean_text(body.question, 500)

    prompt = (
        f"{_PREAMBLE}\n\n{_RULES}\n\n{context}\n\n"
        f"USER QUESTION: {question}\n\nANSWER:"
    )

    try:
        answer = await gemini_generate(prompt, max_output_tokens=800)
    except GeminiError as exc:
        # Never log the prompt/question (may carry PII); just the failure.
        logger.warning("ai_ask_gemini_failed", error=str(exc))
        raise HTTPException(
            status_code=503,
            detail="The AI assistant is busy right now. Please try again in a moment.",
        )

    answer = (answer or "").strip()
    if not answer:
        answer = (
            "I couldn't generate an answer just now — try rephrasing, or open "
            "the dashboard pages directly."
        )
    return AskResponse(answer=answer)
