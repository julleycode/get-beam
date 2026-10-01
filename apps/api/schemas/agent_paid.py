"""Request/response models for the agent-paid internal API (/internal/v1/paid).

These endpoints are called ONLY by the apps/web payment handler after an
MPP/x402 payment is verified. Response models are the PII boundary: they carry
professional/public fields only — never email addresses, phone numbers,
personal social handles, or raw provider payloads. ``extra="forbid"`` on every
request model rejects unknown keys instead of silently ignoring them.
"""

from pydantic import BaseModel, ConfigDict, EmailStr, Field

_STRICT = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ─── Requests ────────────────────────────────────────────────────────────


class EnrichEmailRequest(BaseModel):
    model_config = _STRICT

    email: EmailStr


class IpCompanyRequest(BaseModel):
    model_config = _STRICT

    ip: str = Field(min_length=2, max_length=64)


class DeepResearchRequest(BaseModel):
    model_config = _STRICT

    full_name: str = Field(min_length=1, max_length=200)
    company_name: str | None = Field(default=None, max_length=200)
    job_title: str | None = Field(default=None, max_length=200)
    linkedin_url: str | None = Field(default=None, max_length=500)
    email: EmailStr | None = None


class OutreachDraftRequest(BaseModel):
    model_config = _STRICT

    visitor_name: str = Field(min_length=1, max_length=200)
    visitor_role: str | None = Field(default=None, max_length=200)
    visitor_company: str | None = Field(default=None, max_length=200)
    user_url: str | None = Field(default=None, max_length=500)
    recent_post: str | None = Field(default=None, max_length=4000)


# ─── Responses (PII boundary) ────────────────────────────────────────────


class PaidLocation(BaseModel):
    city: str | None = None
    region: str | None = None
    country: str | None = None


class EnrichEmailResponse(BaseModel):
    full_name: str | None = None
    job_title: str | None = None
    company_name: str | None = None
    company_domain: str | None = None
    linkedin_url: str | None = None
    location: PaidLocation | None = None


class IpCompanyResponse(BaseModel):
    company_name: str | None = None
    domain: str
    confidence: float
    source: str


class DeepResearchResponse(BaseModel):
    summary: str
    researched_at: str
    model: str


class OutreachDraftResponse(BaseModel):
    draft: str
    source: str
