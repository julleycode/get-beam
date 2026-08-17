"""ICP-fit scoring — how well an identified visitor matches the site's REVIEWED
ideal-customer profile.

Beam's copy promises the product tells you which anonymous visitors fit your
ICP. The ICP data lives in ``sites.site_profile`` (the CONFIRMED column, written
only by ``PUT /sites/{id}/analysis``); this module turns it into a single
deterministic 0-100 number.

Schema-v1 shape of ``site_profile`` (transcribed from the authoritative
sanitizer, ``services/site_analysis.py::sanitize_profile``, and the pydantic
models in ``schemas/site_analysis.py``)::

    {
      "summary": str,                     # <= 1000 chars
      "sells": [str],                     # <= 8 items, each <= 300 chars
      "category": str,                    # <= 100 chars
      "sub_industry": str | None,         # <= 100 chars
      "icp": {
        "personas": [                     # <= 3 items
          {"role": str, "pain": str}      # each <= 300 chars
        ],
        "firmographics": {
          "size_band":  str | None,       # FREE LLM TEXT, not an enum
          "industries": [str],            # <= 8 items
          "geography":  [str]             # <= 8 items
        }
      },
      "competitors": [{"name", "domain", "how"}],   # <= 5 items
      "meta": {"v": 1, ...}
    }

Sanitizer guarantees this module relies on: every string has passed
``clean_text`` (``<``/``>`` stripped) and is length-capped; every list is
length-capped; unknown keys are dropped; ``meta.v`` is stamped. It does NOT
guarantee non-empty strings, so every field here is treated as possibly ``""``
or ``None``.

Two facts shape the design:

1. **Provider free text never string-equals LLM-authored ICP text.**
   ``EnrichmentProfile.job_title`` is whatever Hunter/Apollo/PDL returned;
   ``personas[].role`` is whatever Gemini wrote. ``"VP of Engineering"`` vs
   ``"Engineering leader"`` will never match with ``==``. Everything here
   normalizes and scores weighted keyword overlap, never equality.
2. **No per-visitor LLM call.** Cost and latency rule it out, and it would
   break the pure-function philosophy ``conviction.py`` already follows.

PURITY CONTRACT: this module imports stdlib only — no DB session, no ORM, no
network client, no LLM client. Enforced by an AST assertion in
``tests/unit/test_icp_fit.py``.

COPY CONTRACT: callers render ONLY the fixed band vocabulary returned by
:func:`icp_fit_verdict` (:data:`VERDICT_BANDS`). Raw ``site_profile`` strings
(persona ``role``, ``industries[]``, ``size_band``, ``category``) are
LLM-generated from fetched third-party page content — untrusted DISPLAY text,
not merely untrusted prompt text — and are NEVER interpolated into rendered
copy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "IcpFitEstimate",
    "VERDICT_BANDS",
    "estimate_icp_fit",
    "icp_fit_verdict",
    "normalize",
    "score_firmographics",
    "score_geography",
    "score_role",
]

# Tokens that carry no matching signal. Deliberately small — an aggressive
# stopword list would strip real ICP vocabulary ("IT", "ops").
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "at", "by", "for", "from", "in", "into", "of", "on",
        "or", "the", "to", "with",
    }
)

_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")

# Minimum number of dimensions that must produce a real score before a fit
# number is meaningful. Enrichment lands AFTER resolution, which runs AFTER
# aggregation, so at full-recompute time most visitors have no
# EnrichmentProfile row at all — role and firmographics are both None and a
# geography-only number would be presented to the user as "ICP fit". One
# dimension is not a fit assessment.
MIN_SCORED_DIMENSIONS = 2

# Relative weight of each dimension. A dimension that scores None is dropped
# from BOTH the numerator and the denominator, so missing data never drags the
# score down and never shrinks the achievable maximum.
_WEIGHTS: tuple[tuple[str, float], ...] = (
    ("role", 0.5),
    ("firmographics", 0.3),
    ("geography", 0.2),
)

# Fixed band vocabulary. The ONLY strings any UI surface may render for this
# score — see the COPY CONTRACT in the module docstring.
VERDICT_BANDS: tuple[str, ...] = (
    "strong ICP fit",
    "partial ICP fit",
    "weak ICP fit",
)

_STRONG_FIT_AT = 70
_PARTIAL_FIT_AT = 40

# ISO-3166 alpha-2 → country-name + macro-region tokens. `Visitor.country_code`
# is the ONLY geography field on `Visitor` (city/region/country live on
# `IdentifiedVisitor`, a different table this pass deliberately never joins), so
# a bare "us" would score 0 against "United States" and drag the weighted
# average down. Expanding the code first is what makes geography scorable at
# all. A code absent from this map scores None (dropped), never 0.
_ISO_COUNTRY: dict[str, tuple[str, ...]] = {
    "US": ("united", "states", "usa", "america", "north", "american"),
    "CA": ("canada", "canadian", "north", "america"),
    "MX": ("mexico", "mexican", "north", "america", "latin"),
    "BR": ("brazil", "brazilian", "south", "america", "latin", "latam"),
    "AR": ("argentina", "south", "america", "latin", "latam"),
    "GB": ("united", "kingdom", "uk", "britain", "british", "england", "europe", "emea"),
    "IE": ("ireland", "irish", "europe", "emea"),
    "FR": ("france", "french", "europe", "eu", "emea"),
    "DE": ("germany", "german", "deutschland", "europe", "eu", "emea", "dach"),
    "AT": ("austria", "austrian", "europe", "eu", "emea", "dach"),
    "CH": ("switzerland", "swiss", "europe", "emea", "dach"),
    "NL": ("netherlands", "dutch", "holland", "europe", "eu", "emea", "benelux"),
    "BE": ("belgium", "belgian", "europe", "eu", "emea", "benelux"),
    "LU": ("luxembourg", "europe", "eu", "emea", "benelux"),
    "ES": ("spain", "spanish", "europe", "eu", "emea"),
    "PT": ("portugal", "portuguese", "europe", "eu", "emea"),
    "IT": ("italy", "italian", "europe", "eu", "emea"),
    "SE": ("sweden", "swedish", "europe", "eu", "emea", "nordics", "nordic"),
    "NO": ("norway", "norwegian", "europe", "emea", "nordics", "nordic"),
    "DK": ("denmark", "danish", "europe", "eu", "emea", "nordics", "nordic"),
    "FI": ("finland", "finnish", "europe", "eu", "emea", "nordics", "nordic"),
    "PL": ("poland", "polish", "europe", "eu", "emea"),
    "CZ": ("czech", "czechia", "europe", "eu", "emea"),
    "RO": ("romania", "romanian", "europe", "eu", "emea"),
    "GR": ("greece", "greek", "europe", "eu", "emea"),
    "IL": ("israel", "israeli", "middle", "east", "emea"),
    "AE": ("united", "arab", "emirates", "uae", "middle", "east", "emea"),
    "SA": ("saudi", "arabia", "middle", "east", "emea"),
    "ZA": ("south", "africa", "african", "emea"),
    "NG": ("nigeria", "nigerian", "africa", "emea"),
    "KE": ("kenya", "kenyan", "africa", "emea"),
    "IN": ("india", "indian", "asia", "apac"),
    "SG": ("singapore", "asia", "apac", "southeast"),
    "MY": ("malaysia", "asia", "apac", "southeast"),
    "TH": ("thailand", "thai", "asia", "apac", "southeast"),
    "VN": ("vietnam", "vietnamese", "asia", "apac", "southeast"),
    "PH": ("philippines", "asia", "apac", "southeast"),
    "ID": ("indonesia", "asia", "apac", "southeast"),
    "JP": ("japan", "japanese", "asia", "apac"),
    "KR": ("korea", "korean", "asia", "apac"),
    "CN": ("china", "chinese", "asia", "apac"),
    "HK": ("hong", "kong", "asia", "apac"),
    "TW": ("taiwan", "taiwanese", "asia", "apac"),
    "AU": ("australia", "australian", "apac", "oceania", "anz"),
    "NZ": ("new", "zealand", "apac", "oceania", "anz"),
}


@dataclass(frozen=True)
class IcpFitEstimate:
    """Result of scoring one visitor against one site's ICP.

    ``score`` is ``None`` when fewer than :data:`MIN_SCORED_DIMENSIONS`
    dimensions produced a real number — NOT 0, which would claim "scored and a
    poor fit".
    """

    score: int | None
    # (dimension name, 0.0-1.0 score or None) in fixed _WEIGHTS order.
    dimensions: tuple[tuple[str, float | None], ...]
    scored_dimensions: int


def normalize(text: str | None) -> tuple[str, ...]:
    """Lowercase, strip punctuation, tokenize, drop stopwords.

    Returns a deterministically ORDERED, de-duplicated tuple (first-occurrence
    order) — never a set, so callers can never leak set-iteration order into a
    score.
    """
    if not text:
        return ()
    seen: list[str] = []
    for token in _TOKEN_SPLIT_RE.split(text.lower()):
        if not token or token in _STOPWORDS:
            continue
        if token not in seen:
            seen.append(token)
    return tuple(seen)


def _overlap(observed: tuple[str, ...], target: tuple[str, ...]) -> float | None:
    """Fraction of the TARGET (ICP) tokens present in the observed tokens.

    Target-normalised rather than symmetric: a long provider job title should
    not be penalised for carrying tokens the ICP never mentioned.
    """
    if not observed or not target:
        return None
    hits = sum(1 for token in target if token in observed)
    return hits / len(target)


def _best_overlap(
    observed: tuple[str, ...], targets: list[str] | tuple[str, ...] | None
) -> float | None:
    """Best overlap across candidate ICP strings, or None when either side is
    absent. Deterministic: ``max`` over a fixed input order, ties keep the
    first."""
    if not observed or not targets:
        return None
    best: float | None = None
    for target in targets:
        value = _overlap(observed, normalize(target))
        if value is None:
            continue
        if best is None or value > best:
            best = value
    return best


def score_role(
    profile_titles: list[str | None] | tuple[str | None, ...] | None,
    icp_personas: list[dict] | None,
) -> float | None:
    """Weighted keyword overlap between the visitor's job title / seniority and
    the ICP personas' ``role`` text. ``None`` when either side is absent."""
    observed = normalize(" ".join(t for t in (profile_titles or []) if t))
    roles = [
        p.get("role")
        for p in (icp_personas or [])
        if isinstance(p, dict) and p.get("role")
    ]
    return _best_overlap(observed, roles)


def score_firmographics(
    profile: dict | None, firmographics: dict | None
) -> float | None:
    """Industry AND size-band keyword overlap.

    ``size_band`` is FREE LLM TEXT (``str | None``), not an enum — it is matched
    with the same normalize + keyword-overlap machinery as industry. Set or
    equality membership against ``EnrichmentProfile.company_size`` would match
    nothing.

    Each sub-dimension that scores ``None`` is dropped from both sides, exactly
    like a top-level dimension.
    """
    profile = profile or {}
    firmographics = firmographics or {}

    industry = _best_overlap(
        normalize(profile.get("industry")), firmographics.get("industries")
    )
    size_band_text = firmographics.get("size_band")
    size = _best_overlap(
        normalize(profile.get("company_size")),
        [size_band_text] if size_band_text else None,
    )

    scored = [value for value in (industry, size) if value is not None]
    if not scored:
        return None
    return sum(scored) / len(scored)


def score_geography(
    country_code: str | None, geography: list[str] | None
) -> float | None:
    """Overlap between the visitor's country and the ICP's target geographies.

    Input is ``Visitor.country_code`` (ISO-3166 alpha-2) — NOT city/region/
    country, which are ``IdentifiedVisitor`` columns this pass never joins. The
    code is expanded through :data:`_ISO_COUNTRY` before matching; an absent,
    empty or unmapped code returns ``None`` (dropped from both sides), never 0.
    """
    if not country_code or not geography:
        return None
    tokens = _ISO_COUNTRY.get(country_code.strip().upper()[:2])
    if not tokens:
        return None
    return _best_overlap(tokens, geography)


def estimate_icp_fit(
    *,
    site_profile: dict | None,
    job_title: str | None = None,
    seniority_level: str | None = None,
    industry: str | None = None,
    company_size: str | None = None,
    country_code: str | None = None,
) -> IcpFitEstimate:
    """Combine the per-dimension scores into a 0-100 fit.

    Degradation rule: each dimension contributes ``weight * score`` to the
    numerator and ``weight`` to the denominator. A dimension scoring ``None`` is
    dropped from BOTH — never scored as 0, and never shrinking the achievable
    maximum. Final score is ``round(100 * numerator / denominator)``.

    Returns ``score=None`` when fewer than :data:`MIN_SCORED_DIMENSIONS`
    dimensions scored (which subsumes the all-``None`` case).
    """
    profile = site_profile or {}
    icp = profile.get("icp") if isinstance(profile.get("icp"), dict) else {}
    firmographics = (
        icp.get("firmographics") if isinstance(icp.get("firmographics"), dict) else {}
    )

    per_dimension: dict[str, float | None] = {
        "role": score_role([job_title, seniority_level], icp.get("personas")),
        "firmographics": score_firmographics(
            {"industry": industry, "company_size": company_size}, firmographics
        ),
        "geography": score_geography(country_code, firmographics.get("geography")),
    }

    dimensions = tuple((name, per_dimension[name]) for name, _ in _WEIGHTS)
    scored = sum(1 for _, value in dimensions if value is not None)

    if scored < MIN_SCORED_DIMENSIONS:
        return IcpFitEstimate(score=None, dimensions=dimensions, scored_dimensions=scored)

    numerator = 0.0
    denominator = 0.0
    for name, weight in _WEIGHTS:
        value = per_dimension[name]
        if value is None:
            continue
        numerator += weight * value
        denominator += weight

    if denominator <= 0:  # unreachable given the floor above; belt and braces.
        return IcpFitEstimate(score=None, dimensions=dimensions, scored_dimensions=scored)

    return IcpFitEstimate(
        score=round(100 * numerator / denominator),
        dimensions=dimensions,
        scored_dimensions=scored,
    )


def icp_fit_verdict(estimate: IcpFitEstimate | int | float | None) -> str | None:
    """A short human band phrase for conviction copy, or ``None`` when unscored.

    The returned string is ALWAYS a member of :data:`VERDICT_BANDS` — no input
    text is ever echoed back. This is the whole reason the function exists: it
    is the only sanctioned bridge between LLM-authored ICP text and rendered
    product copy.
    """
    score = estimate.score if isinstance(estimate, IcpFitEstimate) else estimate
    if score is None:
        return None
    if score >= _STRONG_FIT_AT:
        return VERDICT_BANDS[0]
    if score >= _PARTIAL_FIT_AT:
        return VERDICT_BANDS[1]
    return VERDICT_BANDS[2]
