"""Agent-provenance sales lead — WS3 (agent-native-revenue) zero-click conversion.

One append-only row per conversion-tool call (``request_quote`` / ``book_demo``)
made against the public MCP surface. This is the ONLY path by which an AI-agent
interaction becomes a real sales lead, and it does so through an EXPLICIT tool
call — never by merging into the human identity graph.

STRUCTURAL ISOLATION GUARANTEE (AC-WS3-4 / program guardrail 1):
this file imports ZERO identity write path. It has no ``visitor_id`` column, no
``email`` column, no ForeignKey to ``IdentifiedVisitor`` / ``Visitor``, and does
not import any identity module. A code reviewer can confirm the isolation by
reading this file's import list alone — an ``AgentLead`` row can never be joined
into ``is_emailable_identity`` and can never become an emailable identity. The
resolved company is a best-effort FREE rDNS domain string only (never a paid
provider result, never a person-level identity).

Mirrors the soft ``site_id: str`` no-FK house convention used by
``AgentVisit`` / ``AgentFetchEvent``. ``id`` / ``created_at`` / ``updated_at``
come from ``Base``.
"""

from sqlalchemy import Boolean, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class AgentLead(Base):
    """Append-only agent-provenance sales lead (one per conversion-tool call)."""

    __tablename__ = "agent_leads"
    __table_args__ = (
        Index("idx_agent_leads_site_created", "site_id", "created_at"),
    )

    site_id: Mapped[str] = mapped_column(String(50), nullable=False)
    # request_quote | book_demo
    tool_name: Mapped[str] = mapped_column(String(30), nullable=False)
    # The 3 qualification params — ALWAYS stored post-sanitization
    # (prompt_safety.clean_text, per Must-Fix 2). Never the raw JSON-RPC values.
    use_case: Mapped[str | None] = mapped_column(String(200), nullable=True)
    company_size: Mapped[str | None] = mapped_column(String(100), nullable=True)
    evaluating_against: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Best-effort company domain from a FREE-ONLY rDNS / cached company_graph
    # lookup at send time (Must-Fix 3). NEVER a paid-provider result. Null when
    # no free hit exists — a datacenter/unresolvable IP stays null (no invented
    # company). A string domain, NOT a Company FK id — this path deliberately
    # never writes a Company/identity row.
    resolved_company_domain: Mapped[str | None] = mapped_column(String(253), nullable=True)
    # Caller IP at conversion time (used for the free lookup; also lets the
    # existing async agent-company-resolution sweep optionally pick it up later
    # under its OWN budget/eligibility gates — never inline here).
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    # Set (to created_at-ish) only on notification SUCCESS. Stays null when the
    # fail-open owner-notification email did not send — the lead row is durable
    # regardless (ACCEPT-AND-RETURN, notification never blocks/500s the response).
    notified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Optional free-text note captured from the caller (sanitized). Kept small.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
