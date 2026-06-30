from pydantic import BaseModel


class CostProviderRow(BaseModel):
    """Spend + call counts for one provider over the window."""

    provider: str
    calls: int
    cost_usd: float
    success_rate: float  # 0..1


class CostCategoryRow(BaseModel):
    """Spend + call counts for one category (identity/enrichment/email/ai/osint)."""

    category: str
    calls: int
    cost_usd: float


class CostDayRow(BaseModel):
    """Spend + call counts bucketed by calendar day (YYYY-MM-DD)."""

    date: str
    calls: int
    cost_usd: float


class IdentityCoverage(BaseModel):
    """How much identity resolution Beam served from its OWN data (free) vs paid
    APIs. The wrapper→owned-asset scoreboard: coverage_rate should trend up as the
    cross-customer graph + deterministic capture grow."""

    owned_calls: int      # successful resolutions from owned data (form/fingerprint/graph/svid)
    paid_calls: int       # successful resolutions from paid providers
    coverage_rate: float  # owned / (owned + paid), 0..1


class CostSummaryResponse(BaseModel):
    """API-cost rollup for a site, read from the unified api_usage_logs ledger.

    Covers identity + enrichment + osint (the instrumented paid sources). All
    money figures are ESTIMATES — see services/api_pricing.py. Identity history
    from before the ledger existed is backfilled from resolution_logs by the
    f7c2e9a4b1d3 migration. Email/AI are not yet instrumented (free tier today).
    """

    site_id: str
    days: int
    total_usd: float
    total_calls: int
    success_calls: int
    failed_calls: int
    by_provider: list[CostProviderRow]
    by_category: list[CostCategoryRow]
    by_day: list[CostDayRow]
    identity_coverage: IdentityCoverage
