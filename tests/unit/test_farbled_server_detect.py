"""WS2 Detector A — server-side fingerprint-mismatch detection.

The detector is a SQL expression evaluated inside the visitor-stub ON CONFLICT
clause in ``apps/api/routers/events.py`` (see FARBLED_MISMATCH_SQL). It lives
there rather than in a preceding SELECT because /ingest is the hottest path in
the API and the comparison needs exactly the two values the upsert already
holds.

That placement means the semantics are only fully observable against a real
Postgres. These unit tests pin two things without one:

1. the truth table, via a faithful Python transcription of the SAME expression
   that is asserted (below) to be textually identical to the shipped SQL — so
   the transcription cannot silently drift from the real predicate; and
2. the invariants that make the detector safe: the ``fingerprint`` column keeps
   its write-once COALESCE, the flag is sticky-OR, and both NULL guards survive.

KNOWN GAP: a live round-trip against Postgres proving the SQL evaluates as
transcribed is Docker-gated and is NOT covered here.

KNOWN GAP (fp3): ``visitors.fingerprint_v3`` values already stored in production
may have been captured while the pixel's audio watchdog fired, i.e. hashed with
``audio=""``. Those rows will mismatch forever against a correctly-measured fp3
from the same browser, and there is no way to identify them retroactively. The
pixel-side fix (suppress fp3 when the render times out) only prevents NEW bad
rows.
"""

import pytest

from apps.api.routers.events import FARBLED_MISMATCH_SQL

pytestmark = pytest.mark.unit


def _mismatch(
    stored_flag: bool,
    stored_fp: str | None,
    incoming_fp: str | None,
    stored_fp3: str | None = None,
    incoming_fp3: str | None = None,
) -> bool:
    """Python transcription of FARBLED_MISMATCH_SQL.

    Kept honest by test_transcription_matches_shipped_sql below: any edit to the
    SQL that this function no longer mirrors fails that test loudly.
    """
    return (
        stored_flag
        or (
            stored_fp is not None
            and incoming_fp is not None
            and stored_fp != incoming_fp
        )
        or (
            stored_fp3 is not None
            and incoming_fp3 is not None
            and stored_fp3 != incoming_fp3
        )
    )


# ─── the truth table ───


def test_rotated_fingerprint_sets_the_flag():
    """Same visitor_id, different fp2 => the fingerprinting surface rotates."""
    assert _mismatch(False, "fp2_aaa", "fp2_bbb") is True


def test_identical_fingerprint_does_not_set_the_flag():
    assert _mismatch(False, "fp2_aaa", "fp2_aaa") is False


def test_brand_new_visitor_is_not_flagged():
    """No stored fp yet = no evidence, not a mismatch."""
    assert _mismatch(False, None, "fp2_aaa") is False


def test_batch_without_a_fingerprint_is_not_flagged():
    """A NULL incoming fp must never be read as 'changed'."""
    assert _mismatch(False, "fp2_aaa", None) is False
    assert _mismatch(False, None, None) is False


def test_flag_is_sticky():
    """Once rotating, always rotating — a later matching fp must not clear it."""
    assert _mismatch(True, "fp2_aaa", "fp2_aaa") is True
    assert _mismatch(True, None, None) is True


# ─── the fp3 truth table ───


def test_rotated_fp3_sets_the_flag_even_when_fp2_matches():
    """The narrow set fp3 adds: fonts/audio randomized, canvas/webgl stable."""
    assert (
        _mismatch(False, "fp2_aaa", "fp2_aaa", "fp3_xxx", "fp3_yyy") is True
    )


def test_identical_fp3_does_not_set_the_flag():
    assert _mismatch(False, "fp2_aaa", "fp2_aaa", "fp3_xxx", "fp3_xxx") is False


def test_fp3_null_on_either_side_is_not_a_mismatch():
    """fp3 lands on a LATER batch than fp2 — a NULL is the normal early state."""
    assert _mismatch(False, "fp2_aaa", "fp2_aaa", None, "fp3_yyy") is False
    assert _mismatch(False, "fp2_aaa", "fp2_aaa", "fp3_xxx", None) is False
    assert _mismatch(False, "fp2_aaa", "fp2_aaa", None, None) is False


def test_both_fp2_and_fp3_differing_sets_the_flag():
    """The ordinary canvas-farbling case: both rotate together."""
    assert _mismatch(False, "fp2_aaa", "fp2_bbb", "fp3_xxx", "fp3_yyy") is True


# ─── invariants that keep the detector safe ───


def test_transcription_matches_shipped_sql():
    """Guards the transcription above against drift from the real predicate."""
    normalized = " ".join(FARBLED_MISMATCH_SQL.split())
    assert normalized == (
        "visitors.has_unstable_fingerprint OR ("
        "visitors.fingerprint IS NOT NULL "
        "AND EXCLUDED.fingerprint IS NOT NULL "
        "AND visitors.fingerprint <> EXCLUDED.fingerprint) OR ("
        "visitors.fingerprint_v3 IS NOT NULL "
        "AND EXCLUDED.fingerprint_v3 IS NOT NULL "
        "AND visitors.fingerprint_v3 <> EXCLUDED.fingerprint_v3)"
    )


def test_both_null_guards_present():
    assert "visitors.fingerprint IS NOT NULL" in FARBLED_MISMATCH_SQL
    assert "EXCLUDED.fingerprint IS NOT NULL" in FARBLED_MISMATCH_SQL


def test_fp3_null_guards_present():
    assert "visitors.fingerprint_v3 IS NOT NULL" in FARBLED_MISMATCH_SQL
    assert "EXCLUDED.fingerprint_v3 IS NOT NULL" in FARBLED_MISMATCH_SQL


def test_expression_is_sticky_or():
    assert FARBLED_MISMATCH_SQL.startswith("visitors.has_unstable_fingerprint OR (")


def test_fingerprint_column_keeps_write_once_coalesce():
    """The detector must READ the discarded value, never overwrite the stored one.

    Overwriting visitors.fingerprint would make every already-known visitor look
    new on every farbled session — the exact damage the flag exists to contain.
    Both fp2 and fp3 must retain their ORIGINAL stored value after a mismatch.
    """
    import pathlib

    src = (
        pathlib.Path(__file__).parent.parent.parent
        / "apps" / "api" / "routers" / "events.py"
    ).read_text(encoding="utf-8")
    assert "COALESCE(visitors.fingerprint, EXCLUDED.fingerprint)" in src
    assert "COALESCE(visitors.fingerprint_v3, EXCLUDED.fingerprint_v3)" in src


def test_write_once_invariant_holds_for_both_columns_on_mismatch():
    """COALESCE semantics: a mismatching batch flags, but never rewrites.

    Transcribes the two COALESCE expressions asserted textually above.
    """

    def coalesce(stored: str | None, incoming: str | None) -> str | None:
        return stored if stored is not None else incoming

    stored_fp, stored_fp3 = "fp2_aaa", "fp3_xxx"
    incoming_fp, incoming_fp3 = "fp2_bbb", "fp3_yyy"

    assert _mismatch(False, stored_fp, incoming_fp, stored_fp3, incoming_fp3) is True
    assert coalesce(stored_fp, incoming_fp) == "fp2_aaa"
    assert coalesce(stored_fp3, incoming_fp3) == "fp3_xxx"


def test_detector_does_not_touch_do_not_resolve():
    """farbled is not a privacy signal; do_not_resolve is GPC and is sticky."""
    assert "do_not_resolve" not in FARBLED_MISMATCH_SQL
