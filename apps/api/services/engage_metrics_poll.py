"""Public-metrics poller for replies Beam posted (engage-learning-agent Phase 1, AC-3).

Reads the engagement counters on OUR OWN replies and records them as outcome
facts. Batched (<=100 ids per call), age-tiered, and hard-capped on call volume.

**Age tiering (E3)** — engagement on a reply is front-loaded, so polling a
month-old reply every hour buys nothing and spends the whole rate budget:

| age of reply    | polled                                  |
|-----------------|-----------------------------------------|
| < 48h           | every sweep                             |
| 48h – 7d        | once per day                            |
| >= 7d           | ONE terminal snapshot, then never again  |

**Latest-wins, not append (N4).** The counters are CUMULATIVE, so `platform_ref`
is the snapshot DAY key (`YYYY-MM-DD`) and a second poll on the same day UPDATEs
that day's row. A second row would double-count in the Phase 3a aggregate; an
error would make the poller look broken. Only the discrete outcome kinds
(`reply_received`, `attributed_visit`) are strictly append-only.

**Call ceiling (E2b).** The 429 backoff in `platforms/base.read_retry` handles
rate-limit RESPONSES; it does nothing about call VOLUME, which a growing reply
corpus inflates without limit. On hitting `engage_metrics_poll_max_calls_per_sweep`
the sweep STOPS and logs the remaining backlog rather than looping unbounded.

Field names are X's real ones (`like_count`, `retweet_count`, `quote_count`,
`reply_count`). `retweet_count` — never an invented `repost_count`.
"""

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.draft import Draft, DraftStatus
from apps.api.models.engage_outcome import EngageOutcome, record_outcome
from apps.api.models.post import Post
from apps.api.models.social_account import SocialAccount

logger = structlog.get_logger()

# Distinct from the sweep's key — the two jobs must be able to run concurrently.
_LOCK_KEY = "engage_metrics_poll"

_BATCH_SIZE = 100
# The ONLY counter names accepted from a platform response. A response whose keys
# are all unrecognized records NOTHING rather than a row of NULLs: an
# invented-but-plausible field name (`repost_count` for X's `retweet_count`) is
# the exact defect that produced a 100% silent skip elsewhere in this repo, and a
# NULL-filled snapshot row would make that skip look like captured data.
_METRIC_FIELDS = ("like_count", "retweet_count", "quote_count", "reply_count")
_FRESH_WINDOW = timedelta(hours=48)
_TERMINAL_AGE = timedelta(days=7)


async def _try_acquire_lock(db: AsyncSession) -> bool | None:
    try:
        result = await db.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": _LOCK_KEY}
        )
        return bool(result.scalar())
    except Exception as exc:  # noqa: BLE001
        logger.warning("engage_metrics_lock_unavailable", error_type=type(exc).__name__)
        return None


async def _release_lock(db: AsyncSession) -> None:
    try:
        await db.execute(
            text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": _LOCK_KEY}
        )
    except Exception:  # noqa: BLE001
        pass


def _day_key(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _is_due(sent_at: datetime | None, now: datetime, polled_days: set[str]) -> bool:
    """Whether this reply should be polled in this sweep (see the tier table)."""
    if sent_at is None:
        return False
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=timezone.utc)
    age = now - sent_at
    today = _day_key(now)
    if age < _FRESH_WINDOW:
        return True
    if age < _TERMINAL_AGE:
        # Daily: skip when today's row already exists.
        return today not in polled_days
    # At/after 7 days: exactly one terminal snapshot, ever.
    return not polled_days


async def run_engage_metrics_poll(db: AsyncSession) -> int:
    """Snapshot public metrics on our sent replies. Returns rows written/updated."""
    if not settings.engage_outcome_capture_enabled:
        return 0

    acquired = await _try_acquire_lock(db)
    if acquired is False:
        logger.info("engage_metrics_poll_lock_busy", key=_LOCK_KEY)
        return 0

    now = datetime.now(timezone.utc)
    day_key = _day_key(now)
    written = 0
    calls_used = 0
    max_calls = max(1, settings.engage_metrics_poll_max_calls_per_sweep)

    try:
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

        # Which snapshot days each draft already has — drives the age tiering
        # without a per-draft query.
        snap_rows = (
            await db.execute(
                select(EngageOutcome.draft_id, EngageOutcome.platform_ref).where(
                    EngageOutcome.outcome_type == "metrics_snapshot"
                )
            )
        ).all()
        polled: dict[object, set[str]] = {}
        for draft_id, ref in snap_rows:
            if ref:
                polled.setdefault(draft_id, set()).add(ref)

        due_by_account: dict[object, dict[str, Draft]] = {}
        for draft, account_id in rows:
            if _is_due(draft.sent_at, now, polled.get(draft.id, set())):
                due_by_account.setdefault(account_id, {})[
                    draft.platform_comment_id
                ] = draft

        backlog = 0
        for account_id, drafts_by_comment in due_by_account.items():
            try:
                account = (
                    await db.execute(
                        select(SocialAccount).where(SocialAccount.id == account_id)
                    )
                ).scalar_one_or_none()
                if account is None:
                    continue

                from apps.api.services.sync import _get_fresh_token

                token = await _get_fresh_token(db, account)
                if not token:
                    continue

                from apps.api.services.platforms import get_platform_service

                service = get_platform_service(account.platform)
            except Exception as exc:
                logger.warning(
                    "engage_metrics_account_failed",
                    account_id=str(account_id)[:8],
                    error_type=type(exc).__name__,
                )
                continue

            comment_ids = list(drafts_by_comment.keys())
            for start in range(0, len(comment_ids), _BATCH_SIZE):
                if calls_used >= max_calls:
                    backlog += len(comment_ids) - start
                    break
                batch = comment_ids[start : start + _BATCH_SIZE]
                try:
                    metrics_by_id = await service.get_tweets_metrics(token, batch)
                    calls_used += 1
                except NotImplementedError:
                    break
                except Exception as exc:
                    calls_used += 1
                    logger.warning(
                        "engage_metrics_batch_failed",
                        error_type=type(exc).__name__,
                        batch_size=len(batch),
                    )
                    continue

                for comment_id, raw_counts in metrics_by_id.items():
                    draft = drafts_by_comment.get(comment_id)
                    if draft is None or not raw_counts:
                        continue
                    counts = {
                        k: v
                        for k, v in raw_counts.items()
                        if k in _METRIC_FIELDS and isinstance(v, int)
                    }
                    if not counts:
                        logger.warning(
                            "engage_metrics_unrecognized_fields",
                            platform_comment_id=comment_id,
                            keys=sorted(raw_counts.keys()),
                        )
                        continue
                    try:
                        did_write = await record_outcome(
                            db,
                            draft_id=draft.id,
                            site_id=draft.site_id,
                            outcome_type="metrics_snapshot",
                            platform_comment_id=comment_id,
                            # Day-granularity key: a re-poll today UPDATEs today's
                            # row instead of colliding or double-writing.
                            platform_ref=day_key,
                            counts=counts,
                            strategy=draft.strategy,
                            observed_at=now,
                        )
                        await db.commit()
                        if did_write:
                            written += 1
                    except Exception as exc:
                        # Per-row fail-open WITH the exception type: a swallowed
                        # InvalidColumnReferenceError (missing partial-index
                        # arbiter) would otherwise look like a healthy sweep that
                        # wrote nothing.
                        await db.rollback()
                        logger.warning(
                            "engage_metrics_row_failed",
                            error_type=type(exc).__name__,
                        )

            if calls_used >= max_calls:
                break

        if backlog:
            logger.info(
                "engage_metrics_poll_ceiling_hit",
                calls_used=calls_used,
                remaining_backlog=backlog,
            )
        logger.info(
            "engage_metrics_poll_done", rows_written=written, calls_used=calls_used
        )
        return written
    except Exception as exc:
        logger.exception("engage_metrics_poll_crashed", error_type=type(exc).__name__)
        return written
    finally:
        if acquired:
            await _release_lock(db)
