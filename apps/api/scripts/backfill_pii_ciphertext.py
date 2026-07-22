#!/usr/bin/env python3
"""Backfill PII ciphertext + blind-index columns for pre-existing rows.

Phase 1 of the PII-encryption-at-rest completion plan
(`process/general-plans/active/pii-at-rest_22-07-26/`).

Columns (`*_ciphertext`, `*_bidx`) and write-side hooks already exist, but rows
created before those shipped have plaintext only. This standalone async script
walks the 4 target tables in batches and populates ciphertext (and blind index,
where a `_bidx` column exists) from the current plaintext value.

Design:
- Per table, iterate rows in batches (default 500) whose ciphertext/bidx is still
  NULL *and* whose plaintext source is present (so a row with NULL plaintext can
  never match forever and spin the loop).
- The per-row transform (`compute_row_updates`) is a pure function — it takes a
  row's current column values and returns the `{column: value}` updates. It is
  field-level idempotent: an already-populated ciphertext/bidx is never rewritten
  (Fernet is non-deterministic, so re-encrypting would needlessly churn the row).
- Idempotent + resumable: the WHERE predicate naturally skips finished rows, so
  a re-run (or a run resumed after a crash) only touches what's left. No in-memory
  checkpoint.
- structlog counts/keys only — a PII value (plaintext or ciphertext) is NEVER
  logged, per repo convention.

CLI:
    python apps/api/scripts/backfill_pii_ciphertext.py                # all tables
    python apps/api/scripts/backfill_pii_ciphertext.py --dry-run      # count only
    python apps/api/scripts/backfill_pii_ciphertext.py --batch-size 1000
    python apps/api/scripts/backfill_pii_ciphertext.py --table visitor_emails

This script is NOT imported by any router/service — it has zero effect on running
application code paths.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Optional

import structlog
from sqlalchemy import and_, func, or_, select, update

from apps.api.models.beam_identity import BeamIdentityNode
from apps.api.models.database import async_session, engine
from apps.api.models.enrichment import EnrichmentProfile
from apps.api.models.visitor import IdentifiedVisitor
from apps.api.models.visitor_email import VisitorEmail
from apps.api.services import pii_crypto

logger = structlog.get_logger()


@dataclass(frozen=True)
class FieldSpec:
    """One PII field to backfill: plaintext source -> ciphertext (+ optional bidx).

    ``bidx`` is set only for email fields (blind-index lookup); social-handle
    fields on enrichment_profiles are ciphertext-only.
    """

    plaintext: str
    ciphertext: str
    bidx: Optional[str] = None


@dataclass(frozen=True)
class TableConfig:
    name: str
    model: Any
    fields: Sequence[FieldSpec]


# Column maps straight from the ORM models (see models/visitor.py,
# models/visitor_email.py, models/beam_identity.py, models/enrichment.py).
TABLE_CONFIGS: dict[str, TableConfig] = {
    "visitor_emails": TableConfig(
        name="visitor_emails",
        model=VisitorEmail,
        fields=[FieldSpec("email", "email_ciphertext", "email_bidx")],
    ),
    "identified_visitors": TableConfig(
        name="identified_visitors",
        model=IdentifiedVisitor,
        fields=[
            FieldSpec("email", "email_ciphertext", "email_bidx"),
            FieldSpec("full_name", "full_name_ciphertext"),
        ],
    ),
    "beam_identity_graph": TableConfig(
        name="beam_identity_graph",
        model=BeamIdentityNode,
        fields=[
            FieldSpec("email", "email_ciphertext", "email_bidx"),
            FieldSpec("full_name", "full_name_ciphertext"),
        ],
    ),
    "enrichment_profiles": TableConfig(
        name="enrichment_profiles",
        model=EnrichmentProfile,
        fields=[
            FieldSpec("linkedin_url", "linkedin_url_ciphertext"),
            FieldSpec("twitter_handle", "twitter_handle_ciphertext"),
            FieldSpec("facebook_url", "facebook_url_ciphertext"),
            FieldSpec("github_url", "github_url_ciphertext"),
        ],
    ),
}


def compute_row_updates(
    fields: Sequence[FieldSpec], row: Mapping[str, Any]
) -> dict[str, str]:
    """Pure per-row transform: return the ciphertext/bidx updates for one row.

    ``row`` maps column name -> current value (plaintext sources AND existing
    ciphertext/bidx values). Returns a ``{column: value}`` dict of the columns
    that should be written. An empty dict means the row is already fully
    backfilled (nothing to do) — this is what makes the backfill idempotent.

    Field-level idempotent: a ciphertext/bidx column that is already populated is
    left untouched (never re-encrypted). A field whose plaintext is empty/None
    contributes no updates.
    """
    updates: dict[str, str] = {}
    for spec in fields:
        plaintext = row.get(spec.plaintext)
        if not plaintext:
            continue
        if row.get(spec.ciphertext) is None:
            ciphertext = pii_crypto.encrypt_pii(plaintext)
            if ciphertext is not None:
                updates[spec.ciphertext] = ciphertext
        if spec.bidx is not None and row.get(spec.bidx) is None:
            # email_hash normalizes internally (strip + lowercase).
            updates[spec.bidx] = pii_crypto.email_hash(plaintext)
    return updates


def _pending_predicate(config: TableConfig):
    """SQL predicate matching rows that still need any ciphertext/bidx populated.

    For each field: (plaintext IS NOT NULL AND ciphertext IS NULL), plus the same
    for bidx where present. The plaintext-not-null guard ensures rows that can
    never be backfilled (NULL plaintext) don't match forever.
    """
    model = config.model
    clauses = []
    for spec in config.fields:
        plaintext_col = getattr(model, spec.plaintext)
        clauses.append(
            and_(plaintext_col.isnot(None), getattr(model, spec.ciphertext).is_(None))
        )
        if spec.bidx is not None:
            clauses.append(
                and_(plaintext_col.isnot(None), getattr(model, spec.bidx).is_(None))
            )
    return or_(*clauses)


def _row_to_mapping(config: TableConfig, obj: Any) -> dict[str, Any]:
    """Extract the columns compute_row_updates needs from an ORM instance."""
    cols: dict[str, Any] = {}
    for spec in config.fields:
        cols[spec.plaintext] = getattr(obj, spec.plaintext)
        cols[spec.ciphertext] = getattr(obj, spec.ciphertext)
        if spec.bidx is not None:
            cols[spec.bidx] = getattr(obj, spec.bidx)
    return cols


async def _count_pending(session, config: TableConfig) -> int:
    stmt = select(func.count()).select_from(config.model).where(
        _pending_predicate(config)
    )
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def backfill_table(
    session, config: TableConfig, *, batch_size: int, dry_run: bool
) -> dict[str, int]:
    """Backfill one table. Returns {rows_scanned, rows_updated, pending_start}."""
    pending_start = await _count_pending(session, config)
    logger.info(
        "backfill_table_start",
        table=config.name,
        pending=pending_start,
        dry_run=dry_run,
        batch_size=batch_size,
    )
    if dry_run:
        return {
            "rows_scanned": 0,
            "rows_updated": 0,
            "pending_start": pending_start,
        }

    model = config.model
    rows_scanned = 0
    rows_updated = 0
    while True:
        stmt = (
            select(model)
            .where(_pending_predicate(config))
            .order_by(model.id)
            .limit(batch_size)
        )
        batch = (await session.execute(stmt)).scalars().all()
        if not batch:
            break

        batch_updated = 0
        for obj in batch:
            rows_scanned += 1
            updates = compute_row_updates(config.fields, _row_to_mapping(config, obj))
            if not updates:
                continue
            await session.execute(
                update(model).where(model.id == obj.id).values(**updates)
            )
            batch_updated += 1
        await session.commit()
        rows_updated += batch_updated

        logger.info(
            "backfill_batch_done",
            table=config.name,
            batch_size=len(batch),
            batch_updated=batch_updated,
            rows_updated_total=rows_updated,
        )

        # Safety: if a full batch produced zero updates, every row in it is
        # unbackfillable (should be excluded by the predicate, but guard against
        # an infinite loop rather than spin).
        if batch_updated == 0:
            logger.warning(
                "backfill_batch_no_updates_stop",
                table=config.name,
                note="batch matched predicate but produced no updates; stopping",
            )
            break

    logger.info(
        "backfill_table_done",
        table=config.name,
        rows_scanned=rows_scanned,
        rows_updated=rows_updated,
    )
    return {
        "rows_scanned": rows_scanned,
        "rows_updated": rows_updated,
        "pending_start": pending_start,
    }


async def run(*, batch_size: int, dry_run: bool, table: Optional[str]) -> None:
    if table is not None and table not in TABLE_CONFIGS:
        raise SystemExit(
            f"Unknown --table {table!r}. Valid: {', '.join(TABLE_CONFIGS)}"
        )
    configs = (
        [TABLE_CONFIGS[table]] if table is not None else list(TABLE_CONFIGS.values())
    )

    totals: dict[str, dict[str, int]] = {}
    async with async_session() as session:
        for config in configs:
            totals[config.name] = await backfill_table(
                session, config, batch_size=batch_size, dry_run=dry_run
            )

    logger.info(
        "backfill_complete",
        dry_run=dry_run,
        pending_by_table={name: t["pending_start"] for name, t in totals.items()},
        updated_by_table={name: t["rows_updated"] for name, t in totals.items()},
    )
    await engine.dispose()


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill PII ciphertext + blind-index columns."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count rows needing backfill; write nothing.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Rows per batch (default: 500).",
    )
    parser.add_argument(
        "--table",
        type=str,
        default=None,
        choices=sorted(TABLE_CONFIGS),
        help="Backfill a single table (default: all 4).",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = _parse_args(argv)
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be >= 1")
    asyncio.run(
        run(batch_size=args.batch_size, dry_run=args.dry_run, table=args.table)
    )


if __name__ == "__main__":
    main()
