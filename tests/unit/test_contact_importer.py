"""Phase 4 unit coverage — CSV parsing, email-format validation, link round-trip.

The DB-backed paths (quota boundary, cross-tenant isolation, merge-on-click)
live in tests/integration/test_contact_import.py and are an environment
known-gap in this sandbox (no Docker/Postgres). Everything provable without a
database is proved here.
"""

import apps.api.main  # noqa: F401 — configures the SQLAlchemy mapper registry

import pytest

from apps.api.services.contact_importer import (
    MAX_FILE_BYTES,
    MAX_IMPORTED_CONTACTS_PER_SITE,
    ContactImportError,
    looks_like_email,
    normalize_email,
    parse_contacts_csv,
)
from apps.api.services.identity_classification import (
    is_emailable_identity,
    is_graph_candidate_provider,
    is_verified_identity,
)
from apps.api.services.link_decorator import decode_bid, generate_bid


# ─── B1a / E5 — CSV email-format validation ──────────────────────────────────


def test_rejects_row_whose_email_cell_is_not_an_email():
    valid, rejected = parse_contacts_csv(b"Ada Lovelace,not-an-email\n")
    assert valid == []
    assert len(rejected) == 1
    assert "no valid email" in rejected[0]["reason"]


def test_accepts_a_well_formed_row_and_normalizes_the_email():
    valid, rejected = parse_contacts_csv(b"Ada Lovelace,Ada@Example.COM\n")
    assert rejected == []
    assert valid == [{"email": "ada@example.com", "full_name": "Ada Lovelace"}]


def test_mixed_file_keeps_good_rows_and_reports_bad_ones():
    raw = b"name,email\nAda,ada@example.com\nBad Row,@@@\nGrace,grace@example.com\n"
    valid, rejected = parse_contacts_csv(raw)
    assert [c["email"] for c in valid] == ["ada@example.com", "grace@example.com"]
    # header row + the malformed row are both reported, never imported
    assert len(rejected) == 2


def test_duplicate_email_within_one_file_is_reported_not_imported_twice():
    valid, rejected = parse_contacts_csv(b"a@x.com\nA@X.com\n")
    assert len(valid) == 1
    assert any(r["reason"] == "duplicate email in file" for r in rejected)


def test_single_column_email_only_file_works():
    valid, _ = parse_contacts_csv(b"solo@example.com\n")
    assert valid == [{"email": "solo@example.com", "full_name": None}]


def test_looks_like_email_edges():
    assert looks_like_email("a@b.co")
    assert not looks_like_email("")
    assert not looks_like_email("a@b")
    assert not looks_like_email("a b@c.com")
    assert normalize_email("  X@Y.COM ") == "x@y.com"


# ─── B1 — defensive caps before any business logic ───────────────────────────


def test_oversized_file_is_rejected_before_parsing():
    with pytest.raises(ContactImportError) as exc:
        parse_contacts_csv(b"x" * (MAX_FILE_BYTES + 1))
    assert exc.value.status_code == 413


def test_business_cap_is_five_thousand():
    assert MAX_IMPORTED_CONTACTS_PER_SITE == 5_000


# ─── D7 / B2a — imported contacts are emailable, verified, non-candidate ─────


def test_is_emailable_identity_true_for_contact_import():
    assert is_emailable_identity("contact_import") is True


def test_contact_import_is_not_a_graph_candidate():
    # The customer supplied this contact — it is verified by definition, never a
    # graph guess awaiting human confirmation.
    assert is_graph_candidate_provider("contact_import") is False
    assert is_verified_identity("identified") is True


def test_agent_and_abuse_guards_still_override_contact_import():
    # is_emailable_identity keeps exactly 3 params and its unconditional guards.
    assert is_emailable_identity("contact_import", "agent-visit-id") is False
    assert is_emailable_identity("contact_import", None, True) is False


# ─── Cross-phase — Phase 2's send-time guard treats imports as verified ──────


def test_phase2_personalization_gate_allows_an_imported_contact():
    """An imported contact is customer-supplied, so it is PERSONALIZABLE.

    The importer writes identity_status="identified" (never "candidate"), which
    is exactly what Phase 2's send-time gate requires. Regression-proves an
    imported contact does not silently fall back to generic copy.
    """
    from apps.api.services.campaign_sender import (
        PersonalizationGateError,
        _assert_personalization_allowed,
        _compose_for_recipient,
    )

    # Must not raise for the tier the importer writes.
    _assert_personalization_allowed("identified", "import:abc", "contact_import")

    subject, body = _compose_for_recipient(
        "identified",
        "Hi {{first_name}}",
        "About {{company_name}}",
        "Ada Lovelace",
        "Analytical Engines",
        visitor_id="import:abc",
        resolution_provider="contact_import",
    )
    assert "Ada" in subject
    assert "Analytical Engines" in body

    # Control: the candidate tier is still refused (Phase 2 unchanged).
    with pytest.raises(PersonalizationGateError):
        _assert_personalization_allowed("candidate", "v-1", "rb2b")


# ─── D4 — tokenized link round-trips through the existing _bid mechanism ─────


def test_imported_contact_link_round_trips(monkeypatch):
    from cryptography.fernet import Fernet

    from apps.api.config import settings

    monkeypatch.setattr(settings, "encryption_key", Fernet.generate_key().decode())
    valid, _ = parse_contacts_csv(b"Ada,ada@example.com\n")
    bid = generate_bid(valid[0]["email"])
    assert decode_bid(bid) == "ada@example.com"
