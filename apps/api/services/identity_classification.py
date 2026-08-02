"""Classify a resolved identity as person-level vs company-level.

Some providers return the ACTUAL visitor (a captured email, a person-graph
match). Others (Hunter, Apollo) only map the visitor's IP to a company domain
and then hand back an ARBITRARY employee at that company (`emails[0]` /
`people[0]`) — that email/name is a company-level guess, NOT the person who
actually visited. The dashboard must label those as company-level so an owner
never mistakes a random employee for their real visitor (or emails them).

Person-level is NOT the same as emailable: probabilistic paid graphs (RB2B,
Leadpipe, Capturify) may still be shown as person-level candidates, but outreach
requires a first-party / owned signal in EMAILABLE_PROVIDERS.
"""

import re

# Providers that return the actual visitor.
PERSON_LEVEL_PROVIDERS = frozenset({
    "form_capture",          # email the visitor typed into a form
    "pdl_person_enrich",     # PDL enrich of a captured email
    "rb2b",                  # US person-level identity graph (candidate — not emailable)
    "leadpipe",              # person-level identity graph (candidate — not emailable)
    "capturify",             # person-level identity graph (candidate — not emailable)
    "manual",                # operator typed it in
    "fingerprint_match",     # Beam graph match on THIS device's fingerprint
    "beam_identity_network", # cross-customer person identity graph
    "svid_reconcile",        # durable server-cookie match to THIS person's prior id
})

# Providers that map IP -> company domain -> an arbitrary employee at that domain.
COMPANY_LEVEL_PROVIDERS = frozenset({"hunter", "apollo"})

# OWNED resolutions: served entirely from Beam's own first-party data, at $0 — no
# external paid API. This is the asset the own-data program grows. Used both to
# write a cost=0 ledger row at resolve time AND to compute the owned-vs-paid
# coverage metric on the costs dashboard. (pdl_person_enrich is NOT here — it
# spends a PDL credit even on a captured email.)
OWNED_FREE_PROVIDERS = frozenset({
    "form_capture",          # the visitor typed their email into a form
    "fingerprint_match",     # same-device match against a prior identification
    "beam_identity_network", # cross-customer person graph hit
    "svid_reconcile",        # durable server-cookie match to this person's prior id
})

# Probabilistic paid person-graphs. May populate IdentifiedVisitor for display,
# but must not drive outreach until a deterministic first-party signal exists.
PAID_PERSON_GRAPH_PROVIDERS = frozenset({"rb2b", "leadpipe", "capturify"})

# Outreach / CRM / hot-alert targets. Paid graphs are intentionally excluded —
# they are candidates, not verified persons (identity P0 quality gates).
EMAILABLE_PROVIDERS = frozenset({
    "form_capture",
    "pdl_person_enrich",
    "manual",
    "fingerprint_match",
    "beam_identity_network",
    "svid_reconcile",
})

# Visitor.identity_status honesty (P1). Legacy ``identified`` is treated as
# verified in readers until rows are rewritten.
STATUS_VERIFIED = "verified"
STATUS_PROVIDER_CANDIDATE = "provider_candidate"
STATUS_IDENTIFIED_LEGACY = "identified"

VERIFIED_STATUSES = frozenset({STATUS_VERIFIED, STATUS_IDENTIFIED_LEGACY})
PROVIDER_CANDIDATE_STATUSES = frozenset({STATUS_PROVIDER_CANDIDATE})
# Has a person-shaped IdentifiedVisitor row (UI enrich gate, list "resolved").
RESOLVED_PERSON_STATUSES = VERIFIED_STATUSES | PROVIDER_CANDIDATE_STATUSES | frozenset({"merged"})

_NAME_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_LOCAL_SPLIT_RE = re.compile(r"[._+\-]+")


def is_owned_resolution(provider: str | None) -> bool:
    """Whether a resolution was served free from Beam's own data (no paid API)."""
    return provider in OWNED_FREE_PROVIDERS


def identity_status_for_provider(provider: str | None) -> str:
    """Map resolution_provider → Visitor.identity_status for a successful save.

    Paid person-graphs → provider_candidate (shown, not trusted).
    Emailable / manual → verified.
    Anything else that still produces an IdentifiedVisitor (e.g. hunter/apollo)
    → provider_candidate so we never mint a new legacy ``identified`` row.
    """
    if provider in EMAILABLE_PROVIDERS or provider == "manual":
        return STATUS_VERIFIED
    return STATUS_PROVIDER_CANDIDATE


def identity_level(provider: str | None) -> str | None:
    """Return 'person', 'company', or None for an identity's resolution_provider."""
    if not provider:
        return None
    if provider in COMPANY_LEVEL_PROVIDERS:
        return "company"
    if provider in PERSON_LEVEL_PROVIDERS:
        return "person"
    return None


def name_email_consistent(full_name: str | None, email: str | None) -> bool:
    """Return True when name and email look like the same person (weak heuristic).

    Used only to reject obvious paid-graph corruption (e.g. Janet Valla vs
    danica_naluz@…). Missing name or email → True (do not reject incomplete rows).
    """
    if not full_name or not email:
        return True
    local = email.strip().lower().split("@", 1)[0]
    if not local:
        return True
    name_tokens = _NAME_TOKEN_RE.findall(full_name.strip().lower())
    if not name_tokens:
        return True
    local_tokens = [t for t in _LOCAL_SPLIT_RE.split(local) if len(t) >= 2]
    # Direct: any name token appears inside the local-part (jsmith, john.smith).
    if any(tok in local for tok in name_tokens):
        return True
    # Reverse: any local token appears inside the full name string.
    name_blob = " ".join(name_tokens)
    if any(tok in name_blob for tok in local_tokens):
        return True
    # Compact initials+surname style: first initial + last name in local
    # (e.g. "jsmith" for "John Smith") — covered by `tok in local` when last
    # name is a name token. If nothing overlapped, treat as inconsistent.
    return False


def is_emailable_identity(
    provider: str | None,
    source_agent_visit_id: str | None = None,
    is_abuse_flagged: bool = False,
) -> bool:
    """Whether an identity may be emailed / exported to ad+CRM / alerted as THE
    visitor.

    AC10 guardrail (highest-priority business safety constraint): an
    agent-classified record — one carrying a ``source_agent_visit_id`` marker —
    can NEVER be an outreach target, regardless of its ``provider``. Agents are
    never emailed; only human/company contacts reached through the existing
    consent/suppression/approval gates may be contacted. This override is checked
    FIRST and unconditionally, so it holds even if such a record were ever
    (incorrectly) tagged with a person-level provider — genuine defense in depth.

    Otherwise: True ONLY for EMAILABLE_PROVIDERS (owned / first-party / manual /
    enrich-of-captured-email). Probabilistic paid person-graphs (rb2b, leadpipe,
    capturify) stay person-level for display but are not outreach targets.
    Company-level guesses (hunter/apollo) and unclassified providers are refused.
    """
    # AC10 override: agent-origin records are never outreach targets, no matter
    # what provider they carry. Checked first, unconditionally.
    if source_agent_visit_id is not None:
        return False
    # Ingest-abuse override (ingest-abuse-hardening AC-4): an identity derived
    # from traffic the ingest layer flagged as flood/abuse is never an outreach
    # target either — the "visitor" it describes is very likely synthetic. Same
    # unconditional, provider-independent shape as the agent guard above, and
    # deliberately gated through this ONE shared helper so a new call site can't
    # drift into checking only half the guardrail.
    if is_abuse_flagged:
        return False
    return provider in EMAILABLE_PROVIDERS
