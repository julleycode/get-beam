"""Drafts router: generate AI drafts, approve/edit/reject, send."""

import asyncio
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

import structlog

from apps.api.dependencies import get_current_user
from apps.api.models.database import get_db
from apps.api.models.draft import Draft, DraftStatus, DraftType
from apps.api.models.post import Post
from apps.api.models.user import User
from apps.api.models.social_account import Platform, SocialAccount
from apps.api.models.voice_example import FeedbackType, VoiceExample

logger = structlog.get_logger()
from apps.api.schemas.drafts import (
    DraftActionResponse,
    DraftEditRequest,
    DraftListResponse,
    DraftResponse,
    GenerateDraftRequest,
    GenerateMultiDraftResponse,
)
from apps.api.services.ai_reply import (
    DRAFT_STRATEGIES,
    determine_draft_mode,
    generate_draft,
    generate_multi_drafts,
    _count_voice_examples,
)
from apps.api.services.sender import send_draft

router = APIRouter(tags=["drafts"])


def _draft_to_response(
    d: Draft,
    original_content: Optional[str] = None,
    original_author: Optional[str] = None,
) -> DraftResponse:
    """Convert a Draft model to DraftResponse schema."""
    strategy_label = None
    if d.strategy and d.strategy in DRAFT_STRATEGIES:
        strategy_label = DRAFT_STRATEGIES[d.strategy]["label"]
    from datetime import datetime, timezone
    return DraftResponse(
        id=str(d.id),
        type=d.type,
        platform=d.platform,
        ai_content=d.ai_content,
        edited_content=d.edited_content,
        status=d.status,
        strategy=d.strategy,
        strategy_label=strategy_label,
        sent_at=d.sent_at,
        created_at=d.created_at or datetime.now(timezone.utc),
        original_content=original_content,
        original_author=original_author,
    )


@router.get("", response_model=DraftListResponse)
async def list_drafts(
    status: Optional[DraftStatus] = None,
    platform: Optional[Platform] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List drafts for the authenticated user, with pagination."""
    base_filter = [Draft.user_id == current_user.id]
    if status:
        base_filter.append(Draft.status == status)
    if platform:
        base_filter.append(Draft.platform == platform)

    count_query = select(func.count(Draft.id)).where(*base_filter)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = (
        select(Draft)
        .options(joinedload(Draft.post))
        .where(*base_filter)
        .order_by(desc(Draft.created_at))
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    result = await db.execute(query)
    drafts = result.unique().scalars().all()

    draft_responses: list[DraftResponse] = []
    for d in drafts:
        original_content = d.post.content if d.post else None
        original_author = d.post.author_username if d.post else None
        draft_responses.append(
            _draft_to_response(d, original_content, original_author)
        )

    return DraftListResponse(drafts=draft_responses, total=total)


@router.post("/generate", response_model=GenerateMultiDraftResponse)
async def generate_new_draft(
    body: GenerateDraftRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate AI draft(s) for a specific post.

    Returns 1-3 drafts depending on GBrain confidence level:
    - Learning mode (< 5 voice examples): 3 drafts with different strategies
    - Confident mode: 1 draft with preferred strategy
    - Staleness check (every 10th): 2 drafts to re-calibrate
    """
    if not body.post_id:
        raise HTTPException(status_code=400, detail="post_id is required")

    # Ownership: only draft against a post on one of the caller's OWN social
    # accounts (Post -> SocialAccount.user_id). Without this any authed user
    # could pass any post_id (IDOR) and burn LLM budget drafting against it.
    post_result = await db.execute(
        select(Post)
        .join(SocialAccount, Post.social_account_id == SocialAccount.id)
        .where(Post.id == body.post_id, SocialAccount.user_id == current_user.id)
    )
    post = post_result.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # Determine mode and strategies
    mode, strategies, _preferred = await determine_draft_mode(
        platform=post.platform,
        db=db,
        user_id=current_user.id,
    )

    voice_count = await _count_voice_examples(db, current_user.id, post.platform)

    logger.info(
        "draft_generation_mode",
        mode=mode,
        strategies=strategies,
        voice_examples=voice_count,
        platform=post.platform.value,
    )

    # Generate drafts. The AI provider (OpenRouter) can be slow or stall: each
    # strategy walks a multi-model fallback chain with a 60s per-model HTTP
    # timeout, so without an outer bound a single request could hang for many
    # minutes and leave the dashboard's "Generating..." button stuck forever.
    # Cap the whole generation so we always return a response the client can
    # react to.
    try:
        draft_results = await asyncio.wait_for(
            generate_multi_drafts(
                platform=post.platform,
                original_content=post.content or "",
                original_author=post.author_username,
                strategies=strategies,
                db=db,
                user_id=current_user.id,
            ),
            timeout=90,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "draft_generation_timeout",
            post_id=str(post.id),
            platform=post.platform.value,
            strategies=strategies,
        )
        raise HTTPException(
            status_code=504,
            detail="Reply generation timed out — the AI provider is slow or "
            "unavailable right now. Please try again in a moment.",
        )

    if not draft_results:
        raise HTTPException(status_code=500, detail="Failed to generate any drafts")

    # Save all drafts to DB
    saved_drafts: list[DraftResponse] = []
    for dr in draft_results:
        draft = Draft(
            id=uuid.uuid4(),
            user_id=current_user.id,
            type=DraftType.comment,
            post_id=post.id,
            platform=post.platform,
            ai_content=dr["content"],
            status=DraftStatus.pending,
            strategy=dr["strategy"],
        )
        db.add(draft)
        saved_drafts.append(
            _draft_to_response(draft, post.content, post.author_username)
        )

    await db.commit()

    return GenerateMultiDraftResponse(
        mode=mode,
        drafts=saved_drafts,
        voice_example_count=voice_count,
    )


@router.put("/{draft_id}/edit", response_model=DraftResponse)
async def edit_draft(
    draft_id: str,
    body: DraftEditRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Edit a draft before approving it."""
    result = await db.execute(
        select(Draft).where(
            Draft.id == draft_id,
            Draft.user_id == current_user.id,
        )
    )
    draft = result.scalar_one_or_none()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft.status not in (DraftStatus.pending,):
        raise HTTPException(status_code=400, detail="Can only edit pending drafts")

    draft.edited_content = body.edited_content
    await db.commit()

    return _draft_to_response(draft)


@router.post("/{draft_id}/approve", response_model=DraftActionResponse)
async def approve_draft(
    draft_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve a draft and send it to the platform.

    Also auto-rejects sibling pending drafts for the same post
    (from multi-draft generation).
    """
    result = await db.execute(
        select(Draft).where(
            Draft.id == draft_id,
            Draft.user_id == current_user.id,
        )
    )
    draft = result.scalar_one_or_none()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft.status != DraftStatus.pending:
        raise HTTPException(status_code=400, detail="Can only approve pending drafts")

    draft.status = DraftStatus.approved
    await db.commit()

    # Auto-reject sibling drafts (other pending drafts for the same post)
    await _auto_reject_siblings(db, draft)

    # Save voice example for GBrain learning
    await _save_voice_example(db, draft)

    # Send immediately
    success = await send_draft(db, draft)
    await db.refresh(draft)

    if success:
        return DraftActionResponse(
            id=str(draft.id),
            status=draft.status,
            message="Draft approved and sent successfully!",
        )
    else:
        raise HTTPException(
            status_code=502,
            detail=f"Draft approved but couldn't be sent to {draft.platform.value}. "
            f"Reconnect your {draft.platform.value} account in Social Accounts and "
            f"try again. Status: {draft.status.value}",
        )


@router.post("/{draft_id}/reject", response_model=DraftActionResponse)
async def reject_draft(
    draft_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reject a draft."""
    result = await db.execute(
        select(Draft).where(
            Draft.id == draft_id,
            Draft.user_id == current_user.id,
        )
    )
    draft = result.scalar_one_or_none()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    draft.status = DraftStatus.rejected
    await db.commit()

    # Save as rejected voice example for GBrain learning
    await _save_voice_example(db, draft)

    return DraftActionResponse(
        id=str(draft.id),
        status=draft.status,
        message="Draft rejected",
    )


# ── Multi-draft: auto-reject siblings ──────────────────

async def _auto_reject_siblings(db: AsyncSession, approved_draft: Draft) -> None:
    """When a draft is approved, reject other pending drafts for the same post."""
    if not approved_draft.post_id:
        return
    try:
        result = await db.execute(
            select(Draft).where(
                Draft.post_id == approved_draft.post_id,
                Draft.user_id == approved_draft.user_id,
                Draft.id != approved_draft.id,
                Draft.status == DraftStatus.pending,
            )
        )
        siblings = result.scalars().all()
        for sibling in siblings:
            sibling.status = DraftStatus.rejected
            await _save_voice_example(db, sibling)
            logger.info(
                "sibling_draft_auto_rejected",
                draft_id=str(sibling.id),
                strategy=sibling.strategy,
            )
        if siblings:
            await db.commit()
    except Exception:
        logger.exception("auto_reject_siblings_failed")


# ── GBrain: voice example collection ──────────────────

async def _save_voice_example(db: AsyncSession, draft: Draft) -> None:
    """Save a voice example from an approved/rejected draft for GBrain learning."""
    try:
        if draft.status == DraftStatus.rejected:
            feedback = FeedbackType.rejected
        elif draft.edited_content and draft.edited_content != draft.ai_content:
            feedback = FeedbackType.edited
        else:
            feedback = FeedbackType.approved

        original_content: Optional[str] = None
        if draft.post_id:
            result = await db.execute(select(Post).where(Post.id == draft.post_id))
            post = result.scalar_one_or_none()
            if post:
                original_content = post.content

        example = VoiceExample(
            id=uuid.uuid4(),
            user_id=draft.user_id,
            platform=draft.platform,
            original_content=original_content,
            ai_draft=draft.ai_content,
            final_content=draft.edited_content or draft.ai_content,
            feedback_type=feedback,
            strategy=draft.strategy,
        )
        db.add(example)
        await db.commit()
        logger.info(
            "voice_example_saved",
            user_id=str(draft.user_id),
            platform=draft.platform.value,
            feedback=feedback.value,
            strategy=draft.strategy,
        )
    except Exception:
        logger.exception("voice_example_save_failed")
        await db.rollback()
