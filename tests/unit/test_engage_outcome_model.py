"""Structural gates on the engage_outcomes table (engage-learning-agent Phase 1).

These assertions guard properties that are cheap to break by accident and
expensive to discover later:

- **No body/text column.** The privacy guarantee for third-party reply content is
  structural, not procedural: if the column cannot exist, no future writer can
  accidentally persist an inbound reply body.
- **`retweet_count`, never `repost_count`.** An invented-but-plausible field name
  is the exact defect that produced a 100% silent skip in the ip-org work.
- **The dedupe index exists in the MODEL, not only the migration.** The
  integration lane builds schema via `Base.metadata.create_all` and never runs
  alembic, so a migration-only index is invisible there and every `ON CONFLICT`
  insert raises `InvalidColumnReferenceError` — which, behind a per-row except,
  looks like a healthy sweep writing nothing.
- **No `contact_bidx`.** That column belongs to Phase 2, together with the
  `blind_index()` helper and its erasure registration. Shipping it here would mean
  un-erasable PII.
"""

import pytest
from sqlalchemy import String, Text

import apps.api.main  # noqa: F401 — registers every ORM model
from apps.api.models.engage_outcome import OUTCOME_TYPES, EngageOutcome

pytestmark = pytest.mark.unit


def _table():
    return EngageOutcome.__table__


def test_no_text_or_body_column_exists():
    table = _table()
    for column in table.columns:
        assert not isinstance(
            column.type, Text
        ), f"engage_outcomes.{column.name} is a Text column — no body may be stored"
        assert "body" not in column.name
        assert "text" not in column.name
        assert "content" not in column.name


def test_contact_bidx_is_not_present_in_this_phase():
    assert "contact_bidx" not in _table().columns


def test_outcome_type_vocabulary_is_closed_and_check_constrained():
    assert OUTCOME_TYPES == (
        "reply_received",
        "metrics_snapshot",
        "attributed_visit",
    )
    check_texts = " ".join(
        str(c.sqltext) for c in _table().constraints if hasattr(c, "sqltext")
    )
    for value in OUTCOME_TYPES:
        assert value in check_texts, f"{value} missing from the CHECK constraint"


def test_metric_columns_use_the_real_platform_field_names():
    columns = set(_table().columns.keys())
    assert {"like_count", "retweet_count", "quote_count", "reply_count"} <= columns
    # The anti-invention half: the plausible-but-wrong alias must NOT exist.
    assert "repost_count" not in columns


def test_both_required_indexes_are_declared_on_the_model():
    by_name = {ix.name: ix for ix in _table().indexes}

    dedup = by_name.get("uq_engage_outcomes_dedup")
    assert dedup is not None, "dedupe index missing from __table_args__"
    assert dedup.unique is True
    assert [c.name for c in dedup.columns] == [
        "draft_id",
        "outcome_type",
        "platform_ref",
    ]
    # PARTIAL — and the predicate must match the migration verbatim, or Postgres
    # cannot infer this index as the ON CONFLICT arbiter.
    predicate = dedup.dialect_options["postgresql"].get("where")
    assert predicate is not None
    assert "platform_ref IS NOT NULL" in str(predicate)

    agg = by_name.get("ix_engage_outcomes_site_strategy_created")
    assert agg is not None, "Phase 3a aggregate index missing"
    assert [c.name for c in agg.columns] == ["site_id", "strategy", "created_at"]


def test_site_id_is_the_nullable_slug_fk_not_the_uuid_pk():
    column = _table().columns["site_id"]
    assert isinstance(column.type, String)
    assert column.type.length == 50
    # Nullable is load-bearing: A1c fail-closed depends on NULL being legal.
    assert column.nullable is True
    targets = {fk.target_fullname for fk in column.foreign_keys}
    assert targets == {"sites.site_id"}, f"site_id must join the slug, got {targets}"


def test_draft_carries_the_internal_phase_1_columns():
    from apps.api.models.draft import Draft

    columns = Draft.__table__.columns
    assert columns["platform_comment_id"].type.length == 64
    assert columns["platform_comment_id"].nullable is True
    assert columns["site_id"].nullable is True
    assert {fk.target_fullname for fk in columns["site_id"].foreign_keys} == {
        "sites.site_id"
    }
