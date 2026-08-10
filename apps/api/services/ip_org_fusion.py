"""Fuse multi-source prefix evidence into one scored organization hypothesis.

This is the module the whole phase exists for. Phase 2 answered "who announces
this prefix?" with a flat 0.45 confidence, no matter how much or how little was
actually known. That number was honest about nothing: an announcement by the
registered holder of exactly that allocation, cryptographically authorized by an
ROA, scored identically to a /24 carved out of some ISP's /16 with no signature
at all.

Fusion scores AGREEMENT ACROSS INDEPENDENT SOURCES. Additive weights, no ML,
every applied signal recorded in ``evidence`` and every missing one recorded in
``uncertainty``, so a consumer can see what the number is made of.

**Purity is a hard contract (AC4.1).** No database, no network, no imports of
either at module scope. Callers do the three queries and pass the results in.
That is what makes every weight row and both clamp boundaries table-testable
without a database.

Two bounds worth understanding before changing anything here:

- The result is clamped to ``[0.05, 0.65]``. The ceiling keeps the PAID
  resolution path (0.7) authoritative — a free, strongly corroborated hit must
  never silently displace data we paid for. It does allow beating rDNS (0.5),
  which is the entire point of corroborating three sources, and is why the
  behavior sits behind ``ip_org_fusion_enabled``.
- ``notfound`` RPKI is scored 0.00, NOT as a penalty. Most of the routing table
  is unsigned; penalizing that would down-rank the majority of legitimate
  corporate prefixes.

There is deliberately NO datacenter/CDN penalty. The v2 lookup filters
``org_kind = 'org'`` before anything reaches this function, so a datacenter, CDN
or eyeball prefix produces no hypothesis at all. Filtering is strictly safer than
penalizing — a penalty still writes a row.
"""

import ipaddress
import time
from typing import Literal, TypedDict

#: Phase-2 parity: the score a lone route_origin row earns, unchanged.
BASE_ROUTE_ORIGIN = 0.45
#: Announced prefix equals its most-specific covering allocation.
W_ALLOCATION_EXACT = 0.15
#: 1-3 bits more specific — too small to tell sub-delegation from ordinary
#: subnetting, so it is explicitly neutral rather than quietly penalized.
W_ALLOCATION_NEUTRAL = 0.00
#: >= 4 bits more specific: the announcing AS is plausibly a provider, not the holder.
W_ALLOCATION_SUBDELEGATED = -0.05
#: Corpus loaded but nothing covers this prefix — a real, evidenced anomaly.
W_ALLOCATION_UNCOVERED = -0.05
#: No RIR corpus at all: absence of evidence, not evidence of absence.
W_NO_CORPUS = 0.00
W_RPKI_VALID = 0.15
W_RPKI_INVALID = -0.20
W_RPKI_NOTFOUND = 0.00

CONFIDENCE_FLOOR = 0.05
CONFIDENCE_CEILING = 0.65

#: The bit-difference at which a more-specific announcement stops looking like
#: ordinary subnetting and starts looking like sub-delegation to a customer.
SUBDELEGATION_BITS = 4

Classification = Literal[
    "disputed_origin",
    "likely_operational_customer",
    "registered_operator",
    "unclassified",
]


class OrgHypothesis(TypedDict):
    """A scored, evidenced claim about which organization holds an address."""

    organization: str
    organization_raw: str | None
    domain: str | None
    classification: str
    confidence: float
    relationship_types: list[str]
    evidence: list[str]
    uncertainty: list[str]


# ── RIR-corpus presence probe cache ──────────────────────────────────────────
#
# Whether ANY registered_holder row exists changes only when an ingest swap runs,
# so re-asking per lookup would add a query to the live resolver path for an
# answer that is stable for days. The value is memoized here with a TTL.
#
# **The TTL is the REAL staleness bound; invalidation is a same-process
# optimization only.** Swaps run in the scheduler job or the one-shot CLI, while
# lookups run in the API web process and across replicas — so for essentially
# every real reader the invalidation call NEVER fires and the TTL is the only
# thing bounding staleness. That is acceptable (a stale ``False`` costs a neutral
# 0.00 and an uncertainty string instead of an evidenced -0.05), but it must not
# be "simplified" later by deleting the TTL on the belief that invalidation
# covers it. It does not.
_CORPUS_CACHE_TTL_SECONDS = 300.0
_corpus_cache: dict[str, float | bool] = {}


def get_cached_rir_corpus_present() -> bool | None:
    """Memoized corpus-present flag, or ``None`` when cold/expired."""
    expires = _corpus_cache.get("expires_at")
    if not isinstance(expires, float) or expires <= time.monotonic():
        return None
    value = _corpus_cache.get("value")
    return value if isinstance(value, bool) else None


def set_cached_rir_corpus_present(value: bool) -> None:
    _corpus_cache["value"] = value
    _corpus_cache["expires_at"] = time.monotonic() + _CORPUS_CACHE_TTL_SECONDS


def invalidate_rir_corpus_cache() -> None:
    """Drop the memoized probe — called at the end of a successful swap."""
    _corpus_cache.clear()


def _masklen(prefix: str) -> int | None:
    try:
        return ipaddress.ip_network(prefix, strict=False).prefixlen
    except (ValueError, TypeError):
        return None


def _most_specific_covering(rir_rows: list[dict]) -> dict | None:
    """The most-specific covering allocation, never an arbitrary one.

    A /8 and a /16 can both cover the same announcement, and they say different
    things about it — so "the covering allocation" must always mean the most
    specific one. Callers normally pre-order this in SQL; re-deriving it here
    keeps the pure function correct on its own terms.
    """
    best: dict | None = None
    best_len = -1
    for row in rir_rows or []:
        length = _masklen(str(row.get("prefix") or ""))
        if length is not None and length > best_len:
            best, best_len = row, length
    return best


def fuse_org_hypothesis(
    route_row: dict | None,
    rir_rows: list[dict] | None,
    rpki_state: str,
    rir_corpus_present: bool,
) -> OrgHypothesis | None:
    """Score one organization hypothesis from the three evidence sources.

    ``route_row`` is the most-specific ``route_origin`` row (already filtered to
    ``org_kind='org'`` by the caller). Without one there is no subject to make a
    claim about, so the result is ``None`` — a registry-only prefix never yields
    a hypothesis.

    ``rir_rows`` are covering ``registered_holder`` rows. Their ``asn`` is NEVER
    read: that evidence class carries no ASN, and the allocation-specificity
    signal is derived purely from prefix lengths.
    """
    if not route_row:
        return None
    organization = str(route_row.get("org_name") or "")
    if not organization:
        return None

    evidence: list[str] = []
    uncertainty: list[str] = []
    relationship_types: list[str] = ["route_origin"]

    score = BASE_ROUTE_ORIGIN
    asn = route_row.get("asn")
    evidence.append(
        f"BGP origin: AS{asn} announces this prefix and is attributed to "
        f"'{organization}'"
        if asn is not None
        else f"BGP origin: this prefix is attributed to '{organization}'"
    )

    # ── Allocation specificity ───────────────────────────────────────────────
    announced_len = _masklen(str(route_row.get("prefix") or ""))
    covering = _most_specific_covering(rir_rows or [])
    covering_len = _masklen(str(covering.get("prefix") or "")) if covering else None
    delta: int | None = None

    if not rir_corpus_present:
        score += W_NO_CORPUS
        uncertainty.append(
            "no RIR allocation corpus is loaded — registration was not cross-checked"
        )
    elif covering is None or covering_len is None or announced_len is None:
        score += W_ALLOCATION_UNCOVERED
        uncertainty.append(
            "the RIR corpus is loaded but no allocation covers this prefix"
        )
    else:
        relationship_types.append("registered_holder")
        delta = announced_len - covering_len
        if delta <= 0:
            score += W_ALLOCATION_EXACT
            evidence.append(
                "the announced prefix matches its registered allocation exactly — "
                "the holder announces its own space"
            )
        elif delta >= SUBDELEGATION_BITS:
            score += W_ALLOCATION_SUBDELEGATED
            uncertainty.append(
                f"the announced prefix is {delta} bits more specific than its "
                "registered allocation — the announcing AS may be a provider "
                "rather than the organization itself"
            )
        else:
            score += W_ALLOCATION_NEUTRAL
            evidence.append(
                f"the announced prefix sits inside a registered allocation "
                f"({delta} bits more specific — within ordinary subnetting)"
            )

    # ── RPKI origin validation ───────────────────────────────────────────────
    if rpki_state == "valid":
        score += W_RPKI_VALID
        relationship_types.append("rpki_authorizer")
        evidence.append(
            "RPKI: the prefix holder cryptographically authorized this origin AS"
        )
    elif rpki_state == "invalid":
        score += W_RPKI_INVALID
        relationship_types.append("rpki_authorizer")
        uncertainty.append(
            "RPKI: a signed authorization covers this prefix and does NOT permit "
            "this origin AS — the announcement is disputed"
        )
    else:
        score += W_RPKI_NOTFOUND
        uncertainty.append(
            "RPKI: no signed authorization exists for this prefix (most of the "
            "routing table is unsigned — this is neutral, not negative)"
        )

    confidence = max(CONFIDENCE_FLOOR, min(CONFIDENCE_CEILING, score))

    return OrgHypothesis(
        organization=organization,
        organization_raw=route_row.get("org_name_raw"),
        # Org-name → domain mapping was split out of this phase into a follow-on
        # plan gated on a coverage measurement. Always None here.
        domain=None,
        classification=derive_classification(
            rpki_state=rpki_state,
            rir_corpus_present=rir_corpus_present,
            covered=covering is not None and covering_len is not None,
            delta=delta,
        ),
        confidence=round(confidence, 4),
        relationship_types=relationship_types,
        evidence=evidence,
        uncertainty=uncertainty,
    )


def derive_classification(
    rpki_state: str,
    rir_corpus_present: bool,
    covered: bool,
    delta: int | None,
) -> Classification:
    """What KIND of relationship this evidence describes. Total and deterministic.

    FIRST MATCHING ROW WINS, top to bottom:

    ==  ====================================================  ==========================
    #   Condition                                             Result
    ==  ====================================================  ==========================
    1   RPKI state is ``invalid``                             ``disputed_origin``
    2   >= 4 bits more specific than covering allocation      ``likely_operational_customer``
    3   equal to the covering allocation                      ``registered_operator``
    4   1-3 bits more specific (the neutral band)             ``likely_operational_customer``
    5   no corpus loaded, or corpus loaded but uncovered      ``unclassified``
    ==  ====================================================  ==========================

    **Row 1 deliberately OVERLAPS rows 2-5** — an RPKI-invalid prefix also has an
    allocation state — and that overlap is precisely why the rule is first-match
    rather than a partition. Rows 2-5 are mutually exclusive and exhaustive among
    THEMSELVES, and row 5 is the total-function fallback, so every input selects
    exactly one row while more than one row may match.
    """
    if rpki_state == "invalid":
        return "disputed_origin"
    if rir_corpus_present and covered and delta is not None:
        if delta >= SUBDELEGATION_BITS:
            return "likely_operational_customer"
        if delta <= 0:
            return "registered_operator"
        return "likely_operational_customer"
    return "unclassified"
