"""Per-call cost estimates for paid external APIs (USD).

ESTIMATES — real pricing varies by plan and volume. These centralize the costs
that were previously hardcoded at the call sites (identity_resolver.py). The
costs dashboard labels everything "estimate". Tune the numbers here in one place.

Failures generally cost $0 (most providers bill per match/credit, not per call).
"""

# provider -> default cost per SUCCESSFUL call (USD).
# 0.0 = on a free tier today (still logged so call counts show; flip the number
# here if the plan changes and spend should start tracking).
_DEFAULT_PRICES: dict[str, float] = {
    # Identity resolution
    "pdl": 0.01,              # People Data Labs person/email enrich
    "pdl_ip": 0.01,          # PDL IP-enrich
    "rb2b": 0.09,
    "leadpipe": 0.0,         # free trial
    "capturify": 0.0,        # free trial
    "hunter": 0.0,           # free tier
    "apollo": 0.0,           # free tier
    "ipinfo": 0.0,           # free tier
    # Enrichment cascade
    "proxycurl": 0.01,       # LinkedIn profile
    "twitter": 0.0,          # bearer-token free tier
    # OSINT
    "osint-industries": 1.0,  # $1 / credit
    # AI / email (free tier today; deferred from instrumentation — see plan P2b)
    "gemini": 0.0,
    "sendgrid": 0.0,
}


def price_for(
    provider: str,
    operation: str | None = None,
    units: int | None = None,
    *,
    success: bool = True,
) -> float:
    """Estimated USD cost of one call. $0 on failure or unknown provider.

    `units` (credits/tokens) multiplies the base price when both are set —
    e.g. an OSINT lookup that burned 2 credits.
    """
    if not success:
        return 0.0
    base = _DEFAULT_PRICES.get(provider, 0.0)
    if units and base:
        return round(base * units, 6)
    return base
