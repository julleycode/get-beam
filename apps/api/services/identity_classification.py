"""Classify a resolved identity as person-level vs company-level.

Some providers return the ACTUAL visitor (a captured email, a person-graph
match). Others (Hunter, Apollo) only map the visitor's IP to a company domain
and then hand back an ARBITRARY employee at that company (`emails[0]` /
`people[0]`) — that email/name is a company-level guess, NOT the person who
actually visited. The dashboard must label those as company-level so an owner
never mistakes a random employee for their real visitor (or emails them).
"""

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


def is_owned_resolution(provider: str | None) -> bool:
    """Whether a resolution was served free from Beam's own data (no paid API)."""
    return provider in OWNED_FREE_PROVIDERS


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
