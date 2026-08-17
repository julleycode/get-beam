"""Reply-back correlation sweep (engage-learning-agent Phase 1, AC-2).

There is no social webhook anywhere in this repo, so detecting that someone
replied to a reply Beam posted has to be poll-based. This sweep reads recent
inbound mentions per connected account and links them to our own replies
EXACTLY — via `referenced_tweets[type=replied_to].id` matched against the stored
`Draft.platform_comment_id` — rather than guessing from timestamps.

Structural model: `agent_handoff_correlation` + `_handoff_correlation_sweep_job`.
The sweep BODY lives here; the job wrapper and `add_job(...)` registration live in
`apps/api/jobs/scheduler.py` (repo convention).

Three properties that matter more than they look:

- **The site's OWN posting account is excluded.** Site owners routinely thread
  follow-ups onto their own replies. Counting those as reply-backs would let a
  site inflate its own track record with zero third-party engagement — and that
  track record is exactly the input Phase 3b's autonomy gate reads.
- **The inbound body is never persisted, and never even passed to the writer.**
  Only the platform id (`platform_ref`) is stored. The inbound AUTHOR is not
  recorded in any form in this phase: the blind-index helper and the erasure
  registration are Phase-2 owned, so recording it now would ship un-erasable PII.
- **Per-row fail-open handlers log the caught exception TYPE.** A bare `except`
  here is the difference between a visible failure and a sweep that looks
  perfectly healthy while writing nothing — asyncpg raises
  `InvalidColumnReferenceError` when an `ON CONFLICT` arbiter index is missing,
  and that is precisely the error a silent swallow would hide.

Never touches the ingest hot path.
"""

from datetime import datetime, timezone

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.draft import Draft, DraftStatus
from apps.api.models.engage_outcome import record_outcome
from apps.api.models.post import Post
from apps.api.models.social_account import SocialAccount

logger = structlog.get_logger()

# Grepped against all existing advisory-lock keys — no collision.
_LOCK_KEY = "engage_outcome_sweep"

# Bound the per-account read so one noisy account cannot dominate a sweep.
_MENTIONS_LIMIT = 100


async def _try_acquire_lock(db: AsyncSession) -> bool | None:
    """True = acquired, False = held elsewhere, None = unsupported/errored."""
    try:
        result = await db.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": _LOCK_KEY}
        )
        return bool(result.scalar())
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "engage_outcome_lock_unavailable", error_type=type(exc).__name__
        )
        return None


async def _release_lock(db: AsyncSession) -> None:
    # Paired with the acquire above: pg_try_advisory_lock is SESSION-scoped, so a
    # per-row commit does NOT release it. Without this the connection returns to
    # the shared 5-connection pool still holding the lock.
    try:
        await db.execute(
            text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": _LOCK_KEY}
        )
    except Exception:  # noqa: BLE001
        pass


def _replied_to_ids(mention: dict) -> list[str]:
    """Extract the ids this mention is a direct REPLY to.

    Only `type == "replied_to"` counts. A quote-tweet or retweet reference is a
    different interaction and must not be recorded as a reply-back.
    """
    refs = mention.get("referenced_tweets") or []
    out: list[str] = []
    for ref in refs:
        if isinstance(ref, dict) and ref.get("type") == "replied_to" and ref.get("id"):
            out.append(str(ref["id"]))
    return out


async def run_engage_outcome_sweep(db: AsyncSession) -> int:
    """Correlate inbound replies to our sent replies. Returns rows written."""
    if not settings.engage_outcome_capture_enabled:
        return 0

    acquired = await _try_acquire_lock(db)
    if acquired is False:
        logger.info("engage_outcome_sweep_lock_busy", key=_LOCK_KEY)
        return 0

    written = 0
    try:
        # Only drafts we actually posted AND whose platform id we captured are
        # correlatable; everything else has no join key.
        rows = (
            await db.execute(
                select(Draft, Post.social_account_id)
                .join(Post, Draft.post_id == Post.id)
                .where(
                    Draft.status == DraftStatus.sent,
                    Draft.platform_comment_id.isnot(None),
                )
            )
        ).all()
        if not rows:
            return 0

        # comment_id -> Draft, grouped per posting account so each account's
        # mentions are read exactly once.
        by_account: dict[object, dict[str, Draft]] = {}
        for draft, account_id in rows:
            by_account.setdefault(account_id, {})[draft.platform_comment_id] = draft

        for account_id, drafts_by_comment in by_account.items():
            try:
                account = (
                    await db.execute(
                        select(SocialAccount).where(SocialAccount.id == account_id)
                    )
                ).scalar_one_or_none()
                if account is None:
                    continue

                # Never read `account.access_token` raw — it is ciphertext, and a
                # ciphertext bearer token yields a silent 401.
                from apps.api.services.sync import _get_fresh_token

                token = await _get_fresh_token(db, account)
                if not token:
                    logger.info(
                        "engage_outcome_sweep_token_unavailable",
                        account_id=str(account_id)[:8],
                    )
                    continue

                from apps.api.services.platforms import get_platform_service

                service = get_platform_service(account.platform)
                mentions = await service.fetch_reply_mentions(
                    token, limit=_MENTIONS_LIMIT
                )
            except NotImplementedError:
                # Platform has no outcome-read support — skip, do not crash.
                continue
            except Exception as exc:
                logger.warning(
                    "engage_outcome_sweep_account_failed",
                    account_id=str(account_id)[:8],
                    error_type=type(exc).__name__,
                )
                continue

            own_platform_user_id = (
                str(account.platform_user_id) if account.platform_user_id else None
            )

            for mention in mentions:
                try:
                    inbound_id = str(mention.get("id") or "")
                    if not inbound_id:
                        continue

                    # Self-inflation guard: a reply authored by the site's OWN
                    # connected account never counts. Compared on the platform
                    # USER ID, not the handle — handles are mutable, ids are not.
                    author_id = mention.get("author_id")
                    if (
                        own_platform_user_id
                        and author_id
                        and str(author_id) == own_platform_user_id
                    ):
                        continue

                    for replied_to in _replied_to_ids(mention):
                        draft = drafts_by_comment.get(replied_to)
                        if draft is None:
                            continue
                        # NOTE: the mention body is deliberately not read here and
                        # is not an argument to record_outcome.
                        did_write = await record_outcome(
                            db,
                            draft_id=draft.id,
                            site_id=draft.site_id,
                            outcome_type="reply_received",
                            platform_comment_id=draft.platform_comment_id,
                            platform_ref=inbound_id,
                            strategy=draft.strategy,
                            observed_at=datetime.now(timezone.utc),
                        )
                        await db.commit()
                        if did_write:
                            written += 1
                except Exception as exc:
                    # Per-row fail-open. The exception TYPE is logged on purpose —
                    # see the module docstring.
                    await db.rollback()
                    logger.warning(
                        "engage_outcome_row_failed",
                        error_type=type(exc).__name__,
                    )

        logger.info("engage_outcome_sweep_done", rows_written=written)
        return written
    except Exception as exc:
        logger.exception(
            "engage_outcome_sweep_crashed", error_type=type(exc).__name__
        )
        return written
    finally:
        if acquired:
            await _release_lock(db)
