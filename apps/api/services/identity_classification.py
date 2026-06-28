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
    "form_capture",       # email the visitor typed into a form
    "pdl_person_enrich",  # PDL enrich of a captured email
    "rb2b",               # US person-level identity graph
    "leadpipe",           # person-level identity graph
    "capturify",          # person-level identity graph
    "manual",             # operator typed it in
})

# Providers that map IP -> company domain -> an arbitrary employee at that domain.
COMPANY_LEVEL_PROVIDERS = frozenset({"hunter", "apollo"})


def identity_level(provider: str | None) -> str | None:
    """Return 'person', 'company', or None for an identity's resolution_provider."""
    if not provider:
        return None
    if provider in COMPANY_LEVEL_PROVIDERS:
        return "company"
    if provider in PERSON_LEVEL_PROVIDERS:
        return "person"
    return None
