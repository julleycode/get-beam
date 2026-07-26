"""Phase 3 / SPEC OQ4 decision (c) — EEA exclusion is GOOGLE-ONLY and FAIL-CLOSED.

G4: an EEA-region visitor is dropped from the Google payload but kept in the
equivalent Meta payload (same segment rows, two provider paths).
G5: a visitor with a null/empty country is ALSO dropped from Google
(fail-closed), and still kept for Meta.

Pure-logic tests against ads_push.exclude_eea_rows plus the provider-branch it
is wired into — no DB, no network.
"""

import pytest

from apps.api.services.ads_push import (
    EEA_COUNTRY_CODES,
    build_hashed_contacts,
    exclude_eea_rows,
)

pytestmark = pytest.mark.unit


def _row(email, country):
    return {"email": email, "country": country}


ROWS = [
    _row("de@example.com", "DE"),        # EEA (Germany)
    _row("fr@example.com", "fr"),        # EEA, lowercase — must still match
    _row("us@example.com", "US"),        # non-EEA
    _row("gb@example.com", "GB"),        # UK is NOT in the EEA post-Brexit
    _row("null@example.com", None),      # unknown country → fail closed
    _row("blank@example.com", "  "),     # unknown country → fail closed
]


def _emails(rows):
    return {r["email"] for r in rows}


# ── G4: EEA rows are excluded for Google ─────────────────

def test_eea_visitors_are_excluded():
    kept = _emails(exclude_eea_rows(ROWS))
    assert "de@example.com" not in kept
    assert "fr@example.com" not in kept


def test_non_eea_visitors_are_kept():
    kept = _emails(exclude_eea_rows(ROWS))
    assert "us@example.com" in kept
    assert "gb@example.com" in kept, "UK left the EEA — it must not be filtered"


# ── G5: unknown country fails CLOSED ─────────────────────

def test_null_and_blank_country_are_excluded_fail_closed():
    kept = _emails(exclude_eea_rows(ROWS))
    assert "null@example.com" not in kept
    assert "blank@example.com" not in kept


def test_missing_country_key_entirely_is_also_excluded():
    assert exclude_eea_rows([{"email": "x@example.com"}]) == []


# ── Google vs Meta: the filter is provider-scoped ────────

def test_google_payload_is_a_strict_subset_of_the_meta_payload():
    """Same segment rows; only the Google path loses the EEA/unknown rows."""
    meta_contacts = build_hashed_contacts(ROWS)
    google_contacts = build_hashed_contacts(exclude_eea_rows(ROWS))

    assert len(meta_contacts) == 6, "Meta must receive every safety-cleared row"
    assert len(google_contacts) == 2  # US + GB only

    meta_hashes = {c.email_sha256 for c in meta_contacts}
    google_hashes = {c.email_sha256 for c in google_contacts}
    assert google_hashes < meta_hashes


def test_push_wires_the_filter_only_into_the_google_branch():
    """Guards against the filter silently leaking onto the Meta path."""
    import inspect

    from apps.api.services import ads_push

    src = inspect.getsource(ads_push.push_segment_to_ads)
    assert 'if provider == "google":' in src
    assert "exclude_eea_rows(rows)" in src
    # Exactly one call site — never applied unconditionally.
    assert src.count("exclude_eea_rows(") == 1


# ── The constant itself ──────────────────────────────────

def test_eea_list_covers_eu27_plus_efta_and_omits_the_uk_and_us():
    assert len(EEA_COUNTRY_CODES) == 30
    for code in ("DE", "FR", "IE", "IS", "LI", "NO"):
        assert code in EEA_COUNTRY_CODES
    for code in ("GB", "US", "CA", "CH"):
        assert code not in EEA_COUNTRY_CODES
