"""Account-level rollup schemas (account-measurement, gap #14).

Counts only — no person-level field (email, name, phone, ip, visitor id) is ever
part of these shapes. Deliberately a NEW module: ``schemas/accounts.py`` holds
the unrelated social-account schemas and must not change.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AccountSort = Literal[
    "last_seen",
    "visitors",
    "identified",
    "sessions",
    "pricing",
    "touched",
    "clicks",
    "conversions",
]

# Reasons the two always-null fields are null — returned with every response.
KNOWN_GAPS: list[str] = [
    "replies: no visitor-keyed reply data exists yet; always null",
    "pipeline_value_cents: CRM pipeline read-back is not built yet; always null",
]

DEFINITIONS: dict[str, str] = {
    "account": "Visitors grouped by their own company_domain (lower-cased). Freemail and empty domains are excluded.",
    "visitors": "Distinct people (canonical id, merged aliases folded) seen in the window (by last_seen).",
    "identified_people": "Distinct people with identity_status identified or merged, seen in the window.",
    "sessions": "Sum of sessions across all of the account's visitor rows (merged rows included) seen in the window.",
    "pageviews": "Sum of pageviews, same scope as sessions.",
    "pricing_visitors": "Distinct people in the window with any page whose path is /pricing or /pricing/...",
    "touched": "Campaign emails sent (status sent, by sent_at) to the account's visitors in the window.",
    "clicks": "Campaign link clicks by the account's visitors in the window (by clicked_at).",
    "conversions": "Conversions by the account's visitors in the window (by occurred_at).",
    "demo_bookings": "Conversions on the 'Demo booked' goal preset.",
    "exclusions": "Agent-derived and abuse-flagged visitor rows are excluded; bot-suspect and agent-operated rows are counted (visibility-only flags).",
    "cross_domain": "A phantom contact and its merged child on different domains appear once in each domain.",
}


class AccountListParams(BaseModel):
    days: int = Field(default=30, ge=1, le=365)
    sort: AccountSort = "last_seen"
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=100)


class AccountRow(BaseModel):
    domain: str
    company_name: str | None = None
    industry: str | None = None
    employee_count: str | None = None
    visitors: int = 0
    identified_people: int = 0
    sessions: int = 0
    pageviews: int = 0
    pricing_visitors: int = 0
    touched: int = 0
    clicks: int = 0
    conversions: int = 0
    demo_bookings: int = 0
    replies: int | None = None
    pipeline_value_cents: int | None = None
    last_seen: datetime | None = None


class AccountListResponse(BaseModel):
    accounts: list[AccountRow]
    total: int
    page: int
    page_size: int
    days: int
    sort: AccountSort
    definitions: dict[str, str] = Field(default_factory=lambda: dict(DEFINITIONS))
    known_gaps: list[str] = Field(default_factory=lambda: list(KNOWN_GAPS))


class AccountCampaign(BaseModel):
    campaign_id: str
    name: str
    touched: int = 0
    clicks: int = 0
    conversions: int = 0


class AccountDetail(AccountRow):
    days: int
    campaigns: list[AccountCampaign] = Field(default_factory=list)
    definitions: dict[str, str] = Field(default_factory=lambda: dict(DEFINITIONS))
    known_gaps: list[str] = Field(default_factory=lambda: list(KNOWN_GAPS))
