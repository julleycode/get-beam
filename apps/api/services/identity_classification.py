"""Classify a resolved identity as person-level vs company-level.

Some providers return the ACTUAL visitor (a captured email, a person-graph
match). Others (Hunter, Apollo) only map the visitor's IP to a company domain
and then hand back an ARBITRARY employee at that company (`emails[0]` /
`people[0]`) — that email/name is a company-level guess, NOT the person who
actually visited. The dashboard must label those as company-level so an owner
never mistakes a random employee for their real visitor (or emails them).
"""

import re


# Providers that return the actual visitor.
PERSON_LEVEL_PROVIDERS = frozenset({
    "form_capture",          # email the visitor typed into a form
    "pdl_person_enrich",     # PDL enrich of a captured email
    "rb2b",                  # US person-level identity graph
    "leadpipe",              # person-level identity graph
    "capturify",             # person-level identity graph
    "manual",                # operator typed it in
    "fingerprint_match",     # Beam graph match on THIS device's fingerprint
    "beam_identity_network", # cross-customer person identity graph
    "svid_reconcile",        # durable server-cookie match to THIS person's prior id
    # Identity-honesty Phase 4: a contact the CUSTOMER uploaded from their own
    # list. Person-level and verified BY DEFINITION — the customer supplied the
    # name/email themselves, it is not an inferred graph match. Deliberately NOT
    # in GRAPH_CANDIDATE_PROVIDERS: an imported contact lands directly on
    # identity_status="identified", never the candidate tier.
    "contact_import",
})

# Providers that map IP -> company domain -> an arbitrary employee at that domain.
COMPANY_LEVEL_PROVIDERS = frozenset({"hunter", "apollo"})

# Identity-honesty Phase 1: providers whose matches are a GRAPH GUESS, never a
# confirmed identity. Every match from one of these lands on
# ``Visitor.identity_status = "candidate"`` regardless of the confidence score —
# no score, however high, ever auto-promotes to "identified". Only a human
# confirmation (the confirm-candidate endpoint) or a deterministic first-party
# signal produces a real "identified".
#
# ``beam_identity_network`` is included even though it is Beam's own data: the
# cross-tenant graph node was itself seeded by whatever provider identified the
# person on the ORIGINATING site, and that origin's tier cannot be cheaply
# re-verified across tenants. A candidate-tier RB2B guess on Site A must not be
# able to resurface as a flat "identified" on Site B, so the conservative
# treatment is applied unconditionally.
#
# Deliberately NOT included: hunter/apollo (already caught by the orthogonal
# company-level axis above — never emailable), form_capture / pdl_person_enrich /
# manual (deterministic first-party or human-entered), svid_reconcile and
# fingerprint_match (deterministic continuity signals — they instead inherit the
# ORIGIN visitor's tier via an explicit origin-status check in the resolver).
GRAPH_CANDIDATE_PROVIDERS = frozenset({
    "rb2b",
    "leadpipe",
    "capturify",
    "beam_identity_network",
})

# PAID person-graphs specifically (main-only, D4: preserved through the
# devjulley/main vocabulary reconciliation). Deliberately NOT the same set as
# GRAPH_CANDIDATE_PROVIDERS above — beam_identity_network is a candidate-tier
# graph but is Beam's OWN free data, so it is not subject to the paid-graph
# name/email corruption gate in identity_resolver.py.
PAID_PERSON_GRAPH_PROVIDERS = frozenset({"rb2b", "leadpipe", "capturify"})

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


def is_owned_resolution(provider: str | None) -> bool:
    """Whether a resolution was served free from Beam's own data (no paid API)."""
    return provider in OWNED_FREE_PROVIDERS


def is_graph_candidate_provider(provider: str | None) -> bool:
    """Whether this provider's matches must land on the candidate tier."""
    return provider in GRAPH_CANDIDATE_PROVIDERS


def is_verified_identity(status: str | None) -> bool:
    """Single source of truth for "is this visitor's identity CONFIRMED?".

    Only ``"identified"`` is verified. ``"candidate"`` is explicitly NOT verified
    — it is an unconfirmed graph guess awaiting human confirm/reject. Every call
    site that previously compared ``identity_status == "identified"`` should use
    this helper so a future tier addition cannot silently widen the meaning of
    "verified" at one site and not another.

    Note this is a separate, orthogonal axis from ``is_emailable_identity()``:
    candidates ARE still emailable/exportable (locked SPEC decision) — they are
    just not *confirmed*, which is what gates personalization and the UI badge.
    """
    return status == "identified"


def identity_level(provider: str | None) -> str | None:
    """Return 'person', 'company', or None for an identity's resolution_provider."""
    if not provider:
        return None
    if provider in COMPANY_LEVEL_PROVIDERS:
        return "company"
    if provider in PERSON_LEVEL_PROVIDERS:
        return "person"
    return None


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

    Otherwise: True ONLY for person-level providers. Company-level guesses
    (hunter/apollo return a random employee at the visitor's company, not the
    visitor) AND any unclassified provider are refused — contacting them spams
    someone who never visited the site (CAN-SPAM / reputation / trust risk). A new
    provider must be added to PERSON_LEVEL_PROVIDERS explicitly to become
    emailable.
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
    return identity_level(provider) == "person"


# --------------------------------------------------------------------------
# Paid-graph name/email consistency gate (main-only, D4: preserved through the
# devjulley/main vocabulary reconciliation — identity_resolver.py's paid-graph
# quality gate depends on this helper and on PAID_PERSON_GRAPH_PROVIDERS above).
# --------------------------------------------------------------------------

_NAME_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_LOCAL_SPLIT_RE = re.compile(r"[._+\-]+")


def name_email_consistent(full_name: str | None, email: str | None) -> bool:
    """Return True when name and email look like the same person (weak heuristic).

    Used only to reject obvious paid-graph corruption (e.g. Janet Valla vs
    danica_naluz@...). Missing name or email -> True (do not reject incomplete rows).
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
