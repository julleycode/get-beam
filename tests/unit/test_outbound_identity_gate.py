"""Phase 9 + P0 (reconciled to the canonical identity vocabulary, D1/D2):
outbound gate — PERSON-LEVEL identities may be emailed / exported to ad+CRM /
alerted; company-level (hunter/apollo) never may.

D2 (locked): graph-candidate providers (rb2b/leadpipe/capturify/
beam_identity_network) ARE person-level and therefore emailable. They are
restrained by the send-time personalization gate (generic copy only until a
human confirms), NOT by an emailability block. main's retired narrow
emailable-providers allow-list is gone.
"""

import pytest

from apps.api.services.identity_classification import (
    COMPANY_LEVEL_PROVIDERS,
    GRAPH_CANDIDATE_PROVIDERS,
    PERSON_LEVEL_PROVIDERS,
    identity_level,
    is_emailable_identity,
)


@pytest.mark.parametrize("provider", sorted(COMPANY_LEVEL_PROVIDERS))
def test_company_level_is_not_emailable(provider):
    assert identity_level(provider) == "company"
    assert is_emailable_identity(provider) is False


@pytest.mark.parametrize("provider", sorted(PERSON_LEVEL_PROVIDERS))
def test_person_level_is_emailable(provider):
    assert identity_level(provider) == "person"
    assert is_emailable_identity(provider) is True


@pytest.mark.parametrize("provider", sorted(GRAPH_CANDIDATE_PROVIDERS))
def test_graph_candidates_are_emailable_not_blocked_by_tier(provider):
    """D2: candidate tier is a CONFIRMATION axis, not an emailability axis."""
    assert identity_level(provider) == "person"
    assert is_emailable_identity(provider) is True


@pytest.mark.parametrize("provider", [None, "", "unknown_future", "ipinfo", "pdl_ip_enrich"])
def test_unknown_provider_is_not_emailable(provider):
    # An unclassified provider defaults to NOT emailable — a new provider must be
    # added to PERSON_LEVEL_PROVIDERS explicitly, so the hole can't silently
    # reopen for anything not yet classified.
    assert is_emailable_identity(provider) is False


def test_real_person_providers_stay_emailable():
    for p in (
        "form_capture",
        "pdl_person_enrich",
        "manual",
        "fingerprint_match",
        "beam_identity_network",
        "svid_reconcile",
        "contact_import",
        # D2: paid graphs are person-level AND emailable; the personalization
        # gate (not an emailability block) is what restrains them.
        "rb2b",
        "leadpipe",
        "capturify",
    ):
        assert p in PERSON_LEVEL_PROVIDERS, p
        assert is_emailable_identity(p) is True, p


def test_hunter_apollo_blocked():
    assert is_emailable_identity("hunter") is False
    assert is_emailable_identity("apollo") is False


# ---------------------------------------------------------------------------
# Identity-honesty Phase 2 — send-time personalization gate (AC15/AC16 + fail-loud)
#
# These exercise the pure composition helpers directly (no DB), mirroring the
# existing `_personalize` / test_personalize.py precedent. The DB wiring itself
# (that send_campaign_emails joins Visitor.identity_status and dispatches on it)
# is proven by tests/integration/test_campaign_mid_send_promotion_cutover.py.
# ---------------------------------------------------------------------------

from apps.api.services.campaign_sender import (  # noqa: E402
    PersonalizationGateError,
    _assert_personalization_allowed,
    _compose_for_recipient,
    _personalize,
)

_SUBJECT_TPL = "Quick idea for {{company_name}}, {{first_name}}"
_BODY_TPL = "Hi {{first_name}},\nSaw {{company_name}} is growing.\nBest,\n[Your Name]"

# The guessed identity a candidate-tier graph provider would hand back.
_GUESSED_NAME = "Janet Fitzgerald"
_GUESSED_COMPANY = "Northwind Robotics"


@pytest.mark.parametrize("status", ["candidate", "anonymous", "unresolvable", None, ""])
def test_candidate_tier_uses_generic_copy(status):
    """AC15: a non-verified recipient never sees a guessed name/company."""
    subject, body = _compose_for_recipient(
        status,
        _SUBJECT_TPL,
        _BODY_TPL,
        _GUESSED_NAME,
        _GUESSED_COMPANY,
        "Julley Thai",
        visitor_id="vis_abcdef123456",
        resolution_provider="rb2b",
    )
    blob = f"{subject}\n{body}"
    for guessed in ("Janet", "Fitzgerald", "Northwind"):
        assert guessed not in blob, guessed
    # Generic greeting + generic company fallback instead.
    assert "Hi there," in body
    assert "your company" in body
    # Sender signature (Beam's own first-party data) is still filled.
    assert "Julley Thai" in body
    assert "{{" not in blob and "[Your Name]" not in blob


def test_identified_tier_uses_personalized_copy():
    """AC16: a verified recipient is personalized byte-identically to today."""
    subject, body = _compose_for_recipient(
        "identified",
        _SUBJECT_TPL,
        _BODY_TPL,
        _GUESSED_NAME,
        _GUESSED_COMPANY,
        "Julley Thai",
        visitor_id="vis_abcdef123456",
        resolution_provider="form_capture",
    )
    assert subject == _personalize(_SUBJECT_TPL, _GUESSED_NAME, _GUESSED_COMPANY, "Julley Thai")
    assert body == _personalize(
        _BODY_TPL, _GUESSED_NAME, _GUESSED_COMPANY, "Julley Thai"
    ).replace("\n", "<br/>")
    assert "Janet" in body and "Northwind Robotics" in body


def test_fail_loud_guard_raises_on_candidate_in_personalized_branch():
    """Defense in depth: entering the personalized branch with a non-verified
    tier raises — it must never silently substitute generic copy and carry on."""
    for status in ("candidate", "anonymous", None, "merged"):
        with pytest.raises(PersonalizationGateError):
            _assert_personalization_allowed(status, "vis_abcdef123456", "rb2b")
    # The verified tier passes through silently.
    assert _assert_personalization_allowed("identified", "vis_abcdef123456", "form_capture") is None


def test_gate_error_message_carries_no_pii():
    """structlog/PII convention: the raised message names the tier, never the
    recipient's guessed name, company, or email."""
    with pytest.raises(PersonalizationGateError) as exc:
        _assert_personalization_allowed("candidate", "vis_abcdef123456", "rb2b")
    msg = str(exc.value)
    assert "candidate" in msg
    assert _GUESSED_NAME not in msg and _GUESSED_COMPANY not in msg
