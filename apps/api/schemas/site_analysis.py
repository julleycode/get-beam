"""Pydantic models for the onboarding site-analysis endpoints.

Caps here mirror the sanitizer in ``services/site_analysis.py`` — the sanitizer is
the enforcement point for LLM output (which never passes through these models),
these constraints are the enforcement point for user-supplied PUT bodies.
"""

from pydantic import BaseModel, Field

PROFILE_SCHEMA_VERSION = 1

SUMMARY_MAX = 1000
CATEGORY_MAX = 100
ITEM_MAX = 300
MAX_SELLS = 8
MAX_PERSONAS = 3
MAX_COMPETITORS = 5


class Persona(BaseModel):
    role: str = Field(default="", max_length=ITEM_MAX)
    pain: str = Field(default="", max_length=ITEM_MAX)


class Firmographics(BaseModel):
    size_band: str | None = Field(default=None, max_length=ITEM_MAX)
    industries: list[str] = Field(default_factory=list, max_length=MAX_SELLS)
    geography: list[str] = Field(default_factory=list, max_length=MAX_SELLS)


class Icp(BaseModel):
    personas: list[Persona] = Field(default_factory=list, max_length=MAX_PERSONAS)
    firmographics: Firmographics = Field(default_factory=Firmographics)


class Competitor(BaseModel):
    name: str = Field(default="", max_length=ITEM_MAX)
    # LLM-controlled free text. Hostname-validated with a POSITIVE check in
    # sanitize_profile; rendered as PLAIN TEXT by the UI, never as an <a href>.
    domain: str | None = Field(default=None, max_length=ITEM_MAX)
    how: str = Field(default="", max_length=ITEM_MAX)


class ProfileConfidence(BaseModel):
    summary: float | None = None
    icp: float | None = None
    competitors: float | None = None


class ProfileMeta(BaseModel):
    # JSONB schema version — bump on any shape change. Written on EVERY persisted
    # profile (candidate and confirmed) and by mock_profile.
    v: int = PROFILE_SCHEMA_VERSION
    analyzed_at: str | None = None
    model: str | None = None
    mode: str | None = None  # "grounded" | "mock"
    confidence: ProfileConfidence = Field(default_factory=ProfileConfidence)
    unknown: list[str] = Field(default_factory=list)
    user_edited: bool = False


class SiteProfile(BaseModel):
    summary: str = Field(default="", max_length=SUMMARY_MAX)
    sells: list[str] = Field(default_factory=list, max_length=MAX_SELLS)
    category: str = Field(default="", max_length=CATEGORY_MAX)
    sub_industry: str | None = Field(default=None, max_length=CATEGORY_MAX)
    icp: Icp = Field(default_factory=Icp)
    competitors: list[Competitor] = Field(default_factory=list, max_length=MAX_COMPETITORS)
    meta: ProfileMeta = Field(default_factory=ProfileMeta)


class BudgetOut(BaseModel):
    used: int
    limit: int | None
    allowed: bool
    # `is_byok` is deliberately ABSENT — this meter is not BYOK-exempt, so the
    # field would be permanently False and would invite a future exemption.


class SiteAnalysisOut(BaseModel):
    site_id: str
    status: str  # "none" | "pending" | "ready" | "failed" (derived)
    profile: SiteProfile | None = None
    candidate: SiteProfile | None = None
    analyzed_at: str | None = None
    # DERIVED at read time from (budget.allowed, derived status). There is no
    # `message` column and nothing persists it.
    message: str | None = None
    # POST-only signal; always False on GET.
    already_running: bool = False
    budget: BudgetOut


class SiteAnalysisConfirm(BaseModel):
    profile: SiteProfile
    # Fail-safe default: the client must PROVE the current description is empty
    # (or that the user explicitly chose "replace") to send True.
    apply_description: bool = False
    apply_category: bool = True
    # False = DISMISS only: NULL the candidate and touch nothing else.
    promote: bool = True
