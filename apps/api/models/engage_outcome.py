"""Append-only outcome facts for replies Beam posted (engage-learning-agent Phase 1).

One row = one observed fact about a reply Beam sent. Three fact kinds live here,
distinguished by ``outcome_type``:

- ``reply_received``    — a third party replied back to our reply (discrete event)
- ``metrics_snapshot``  — the public engagement counters on our reply, per day
- ``attributed_visit``  — a site visit carrying our minted attribution tag

**FAIL-CLOSED ON NULL ``site_id`` (A1c — binding across the whole program).**
``Draft.site_id`` is nullable by design (a multi-site user's manual draft cannot
be resolved to one site), and when it is NULL the safe direction is to do
nothing rather than guess: no attribution mint (Phase 1 Step C), no autonomy
eligibility (Phase 3b), and every site aggregate EXCLUDES NULL-site rows
(Phase 3a). Phases 2 and 3 inherit this rule from here.

**Site key is the SLUG, not the UUID PK (N1).** ``site_id`` is ``String(50)``
referencing ``sites.site_id`` — the same key ``visitors.site_id``,
``events.site_id`` and ``engagement_attributions.site_id`` already use. Downstream
joins go to ``sites.site_id`` directly, NEVER to ``sites.id``.

**No body/text column may ever exist on this table (AC-6 precursor).** An inbound
reply's body is never persisted, never passed into ``record_outcome``, and never
logged. ``platform_ref`` holds an *id* (or a date key), which is not a body.

**No ``contact_bidx`` in this phase (N5/N6).** The ``blind_index()`` helper and
the erasure machinery (``ERASURE_TARGETS``, ``graph_erasure.py``) are Phase-2
owned. Adding a PII-derived column here would ship un-erasable PII AND create a
circular phase dependency. Phase 2 adds the column, its migration, and its
erasure registration together.
"""

import uuid
from datetime import datetime
from typing import Optional

import structlog
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base

logger = structlog.get_logger()

# Closed vocabulary. Enforced twice on purpose: a CHECK constraint at the DB tier
# (so a stray writer cannot invent a fourth kind) and this tuple for callers.
OUTCOME_TYPES: tuple[str, ...] = (
    "reply_received",
    "metrics_snapshot",
    "attributed_visit",
)

# Only cumulative counters are latest-wins; discrete events are append-only.
# Re-observing a metrics snapshot on the same day must UPDATE that day's row —
# a second row would double-count in the Phase 3a aggregate, and raising would
# make the poller look broken. Discrete events must NOT update: an overwrite
# would destroy history.
_UPSERT_TYPES: frozenset[str] = frozenset({"metrics_snapshot"})

# Mirrors the partial unique index predicate below. Postgres can only infer a
# PARTIAL index as an ON CONFLICT arbiter when the statement repeats the
# predicate verbatim, so this constant is shared by the index and the upsert
# rather than written twice.
_DEDUP_PREDICATE = "platform_ref IS NOT NULL"


class EngageOutcome(Base):
    __tablename__ = "engage_outcomes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Nullable per A1c fail-closed. FK targets the unique SLUG column (N1).
    site_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("sites.site_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("drafts.id", ondelete="CASCADE"), nullable=False
    )
    platform_comment_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    outcome_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # Dedupe key. The inbound reply's platform id (reply_received), the snapshot
    # day key YYYY-MM-DD (metrics_snapshot), or the visit reference
    # (attributed_visit). Nullable so a row that genuinely has no stable
    # reference can still be recorded — it just does not participate in dedupe.
    platform_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # X's real field names. `retweet_count` is deliberate — an invented
    # `repost_count` is the exact ip-org defect that produced a 100% silent skip.
    like_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    retweet_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    quote_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reply_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Denormalized from Draft.strategy so the Phase 3a per-playbook aggregate is
    # a single-table scan. playbook == Draft.strategy (pinned here).
    strategy: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    observed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "outcome_type IN ('reply_received', 'metrics_snapshot', 'attributed_visit')",
            name="ck_engage_outcomes_outcome_type",
        ),
        # Dedupe identity. PARTIAL because a row with no stable reference must
        # stay recordable rather than collapse onto other NULL-ref rows.
        #
        # Declared HERE as well as in the migration on purpose: the integration
        # lane builds its schema via ``Base.metadata.create_all``
        # (``tests/conftest.py``), never via alembic. A migration-only index is
        # therefore invisible to every integration test, and the metrics upsert
        # would raise asyncpg ``InvalidColumnReferenceError`` ("no unique or
        # exclusion constraint matching the ON CONFLICT specification") — which,
        # behind a per-row except, looks like a healthy sweep writing nothing.
        # The predicate text must match the migration's verbatim.
        Index(
            "uq_engage_outcomes_dedup",
            "draft_id",
            "outcome_type",
            "platform_ref",
            unique=True,
            postgresql_where=text(_DEDUP_PREDICATE),
        ),
        # Required by the Phase 3a per-site/per-playbook aggregate. NOTE for
        # Phase 3a (K6): the leading column may be largely NULL on the
        # manual-draft path, so re-check selectivity once real data exists.
        Index(
            "ix_engage_outcomes_site_strategy_created",
            "site_id",
            "strategy",
            "created_at",
        ),
    )


async def record_outcome(
    db: AsyncSession,
    *,
    draft_id: uuid.UUID,
    site_id: Optional[str],
    outcome_type: str,
    platform_comment_id: Optional[str] = None,
    platform_ref: Optional[str] = None,
    counts: Optional[dict[str, Optional[int]]] = None,
    strategy: Optional[str] = None,
    observed_at: Optional[datetime] = None,
) -> bool:
    """Write one outcome fact. Returns True when a row was inserted or updated.

    NEVER accepts a text/body argument — that is the structural half of AC-6.
    ``counts`` carries only the four integer engagement counters.

    Write semantics differ by kind (A3b):
    - ``metrics_snapshot`` → ON CONFLICT DO UPDATE (latest-wins; the counters are
      cumulative, so a same-day re-poll must refresh the day's row).
    - everything else → ON CONFLICT DO NOTHING (discrete events; an update would
      destroy history).

    Raises on a DB error. Callers own the fail-open decision so they can log the
    exception TYPE — a bare swallow here would hide a missing arbiter index.
    """
    if outcome_type not in OUTCOME_TYPES:
        raise ValueError(f"unknown outcome_type: {outcome_type!r}")

    counts = counts or {}
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "draft_id": draft_id,
        "site_id": site_id,
        "outcome_type": outcome_type,
        "platform_comment_id": platform_comment_id,
        "platform_ref": platform_ref,
        "like_count": counts.get("like_count"),
        "retweet_count": counts.get("retweet_count"),
        "quote_count": counts.get("quote_count"),
        "reply_count": counts.get("reply_count"),
        "strategy": strategy,
        "observed_at": observed_at,
    }

    stmt = pg_insert(EngageOutcome).values(**values)
    if outcome_type in _UPSERT_TYPES:
        stmt = stmt.on_conflict_do_update(
            index_elements=["draft_id", "outcome_type", "platform_ref"],
            # MUST mirror the partial index predicate or Postgres cannot infer
            # the arbiter (Q1/E12; precedent agent_visit_persistence.py).
            index_where=text(_DEDUP_PREDICATE),
            set_={
                "like_count": stmt.excluded.like_count,
                "retweet_count": stmt.excluded.retweet_count,
                "quote_count": stmt.excluded.quote_count,
                "reply_count": stmt.excluded.reply_count,
                "observed_at": stmt.excluded.observed_at,
                "updated_at": func.now(),
            },
        )
    else:
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["draft_id", "outcome_type", "platform_ref"],
            index_where=text(_DEDUP_PREDICATE),
        )

    result = await db.execute(stmt.returning(EngageOutcome.id))
    return result.scalar_one_or_none() is not None
