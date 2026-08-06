from datetime import datetime

from sqlalchemy import DateTime, Float, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class JobChangeEvent(Base):
    """One row per CONFIRMED job change for a same-tenant identified visitor.

    Minimal before/after pair, not a history log: the "current" professional
    fields keep living on ``EnrichmentProfile`` (overwritten in place, existing
    behavior); this table records only the transition itself so the dashboard,
    the segmenter and the draft-outreach trigger have something durable to point
    at.

    NO PII BY CONSTRUCTION (SPEC AC-14): there is no email column and no
    name column. The person is referenced by the ``(site_id, visitor_id)``
    string pair only — plaintext identity stays in ``visitor_emails`` /
    ``IdentifiedVisitor`` / ``EnrichmentProfile``, which are the sole PII
    holders. Company/job-title strings are ORGANIZATION attributes, not personal
    identifiers.

    SAME-TENANT ONLY (AC-11): rows are scoped by ``site_id`` and are never read
    from or written to ``beam_identity_graph``. Cross-tenant job-change
    propagation is explicitly out of scope for v1.

    No FK constraint onto ``visitors`` / ``enrichment_profiles`` — the same
    string-pair, no-hard-FK convention already used by ``EnrichmentProfile``,
    ``IdentitySignal`` and ``CompanyGraphNode``, which avoids migration-order
    coupling. Erasure is therefore explicit, not cascading: this table is listed
    in ``visitors.delete_visitor_data``'s DELETE-loop tuple (AC-12).

    The ``(site_id, visitor_id)`` index is deliberately NOT unique — a visitor
    can legitimately change jobs more than once over time, and AC-7 asks for one
    row per detected transition.

    ``id`` / ``created_at`` / ``updated_at`` come from ``Base``.
    """

    __tablename__ = "job_change_events"
    __table_args__ = (
        Index("idx_job_change_site_visitor", "site_id", "visitor_id"),
        Index("idx_job_change_site_detected", "site_id", "detected_at"),
    )

    site_id: Mapped[str] = mapped_column(String(50), nullable=False)
    visitor_id: Mapped[str] = mapped_column(String(100), nullable=False)

    # Before/after pair. Company is required (a change with no prior company is
    # a first-time enrichment, not a job change, and is filtered upstream).
    prior_company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    new_company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    prior_job_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    new_job_title: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Source-tier confidence at detection time (uncalibrated heuristic — see
    # the plan's Known-Gap #2; do NOT read these as validated thresholds).
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Which independent signal corroborated the change:
    # "work_email_domain" | "company_graph_ip" | "work_email_domain+company_graph_ip"
    corroboration_signal: Mapped[str | None] = mapped_column(String(100), nullable=True)

    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
