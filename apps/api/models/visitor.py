import uuid
from datetime import datetime

from sqlalchemy import Boolean, String, Text, DateTime, Float, Integer, Index, and_, func, or_
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class Visitor(Base):
    __tablename__ = "visitors"
    __table_args__ = (
        Index("idx_visitors_site_intent", "site_id", "intent_score"),
        Index("idx_visitors_identity_status", "site_id", "identity_status"),
        Index("idx_visitors_site_enrichment", "site_id", "enrichment_status"),
        Index("idx_visitors_site_ai_source", "site_id", "ai_source"),
        Index("uq_visitors_site_visitor", "site_id", "visitor_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(String(50), nullable=False)
    visitor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    total_pageviews: Mapped[int] = mapped_column(Integer, default=0)
    total_sessions: Mapped[int] = mapped_column(Integer, default=0)
    avg_time_on_page: Mapped[float] = mapped_column(Float, default=0.0)
    max_scroll_depth: Mapped[int] = mapped_column(Integer, default=0)
    pages_visited: Mapped[list[str]] = mapped_column(JSONB, default=list)
    top_referrer: Mapped[str | None] = mapped_column(String(500))
    # Chronologically-first pageview referrer (true first-touch). top_referrer is
    # MAX(referrer) = lexicographic, unusable for attribution — this is the real
    # entry referrer, set by the aggregator's ARRAY_AGG(... ORDER BY created_at).
    first_touch_referrer: Mapped[str | None] = mapped_column(String(500))
    # AI answer-engine attribution label derived from first_touch_referrer via
    # classify_ai_source(). ADDITIVE ATTRIBUTION METADATA ONLY — never sets
    # source_agent_visit_id, never gates emailability or any guardrail.
    ai_source: Mapped[str | None] = mapped_column(String(30))
    utm_source: Mapped[str | None] = mapped_column(String(200))
    utm_medium: Mapped[str | None] = mapped_column(String(200))
    country_code: Mapped[str | None] = mapped_column(String(5))
    device_type: Mapped[str | None] = mapped_column(String(20))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    company_domain: Mapped[str | None] = mapped_column(String(253))
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    canonical_visitor_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Durable server-set identity (_rta_svid HttpOnly cookie). When a returning
    # visitor's CLIENT id is wiped (Safari ITP caps client cookies/localStorage at
    # 7 days), the server cookie still carries the ORIGINAL visitor_id. Stored
    # write-once so the resolver can recover a prior identification for FREE
    # instead of re-paying a provider to re-identify someone we already own.
    server_visitor_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    intent_score: Mapped[float] = mapped_column(Float, default=0.0)
    identity_status: Mapped[str] = mapped_column(String(30), default="anonymous")
    enrichment_status: Mapped[str] = mapped_column(String(20), default="pending")
    segmented: Mapped[bool] = mapped_column(Boolean, default=False)
    # Privacy: visitor signaled GPC/DNT (or was added to a suppression list).
    # When true, identity resolution must NEVER run for this visitor. Sticky:
    # once set by any event, the aggregator keeps it true on recompute.
    do_not_resolve: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    # EvalLayer Phase 05: True for a synthetic Visitor row created by the
    # agent-company-resolution sweep (visitor_id = f"agent:{agent_visit.id}").
    # Every human-facing query excludes these via human_only_visitor_filter()
    # (SPEC AC2) so agent-derived rows never pollute human visitor data, stats,
    # resolution eligibility, or segmentation.
    is_agent_derived: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    # Ingest abuse marker, aggregated from events.is_flagged_abuse via
    # BOOL_OR in aggregate_visitors_for_site. Sticky on recompute (OR-merged on
    # conflict), exactly like do_not_resolve: once a visitor's traffic looked
    # like a flood, a later clean window must not launder it back to emailable.
    is_abuse_flagged: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    # Cadence bot flag (visibility-only, see cadence_bot_flag.py) — structurally
    # independent of is_abuse_flagged; never read by is_emailable_identity();
    # never excluded from any aggregate FILTER clause. Set by the batch sweep
    # only (cadence_bot_flag_sweep.py), never on the ingest hot path. Sticky:
    # OR-merged, a later clean window never un-flags.
    is_bot_suspect: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    # Outlier / internal-traffic damping (see outlier_traffic_damping.py).
    # Visibility + damping signal: a visitor whose event volume is a statistical
    # outlier WITHIN this site, sustained across days, WITH engagement present.
    #
    # DELIBERATELY NOT STICKY, unlike is_bot_suspect / is_abuse_flagged above.
    # Those two are one-way OR-merged forever; this one is not, and must never
    # be OR-merged into an aggregate upsert. A false positive here silently
    # removes a genuine hot prospect from the customer's dashboard aggregates
    # AND deprioritises them for identity resolution — so it MUST be reversible.
    #
    # Never read by is_emailable_identity(); never affects outreach eligibility.
    # This is a data-quality signal, not a contactability one.
    is_internal_suspect: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    # Manual tri-state override on is_internal_suspect. The human's call always
    # wins over the automatic scorer, PERMANENTLY and in BOTH directions:
    #   None            — no manual action; the automatic sweep may evaluate.
    #   "internal"      — user said "this is me / my team". Sweep must never
    #                     un-set it.
    #   "not_internal"  — user explicitly rejected an automatic flag. Sweep must
    #                     never re-flag it.
    # The sweep skips ANY visitor with a non-NULL override — that skip is the
    # enforcement mechanism for the both-directions rule.
    internal_override: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Provider-outage deferral watermark. Set when every provider tier that
    # could have identified this visitor was down: the row stays `anonymous`
    # (retryable) instead of going `unresolvable` (terminal), and every sweep
    # skips it until the timestamp passes. NULL = not deferred.
    #
    # This has to be a COLUMN, not a Redis breaker: the scarce resource is the
    # per-site sweep slot (LIMIT 20 / LIMIT 50, ordered by intent_score DESC),
    # and only a column can join the sweep's WHERE clause. Deferred visitors
    # keep gaining intent, so without this filter a long outage parks them at
    # the top of every batch and new visitors never get looked at.
    resolution_deferred_until: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    # How many times this visitor has been deferred; indexes into the backoff
    # schedule (identity_resolver.RESOLUTION_DEFER_BACKOFF). Past the last step
    # the visitor goes `unresolvable` — an outage that long is a dead
    # credential, which waiting does not fix. Reset to 0 on any terminal write.
    resolution_defer_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class IdentifiedVisitor(Base):
    __tablename__ = "identified_visitors"
    __table_args__ = (
        Index("uq_identified_site_visitor", "site_id", "visitor_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    visitor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    site_id: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    full_name: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    city: Mapped[str | None] = mapped_column(String(100))
    region: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str | None] = mapped_column(String(5))
    gender: Mapped[str | None] = mapped_column(String(20))
    age_range: Mapped[str | None] = mapped_column(String(20))
    resolution_provider: Mapped[str | None] = mapped_column(String(50))
    confidence_score: Mapped[float | None] = mapped_column(Float)
    do_not_email: Mapped[bool] = mapped_column(default=False)
    # EvalLayer Phase 05 / Phase 07 guard: the unforgeable agent-origin marker.
    # Stored as the AgentVisit.id UUID *string* (matches the str | None signature
    # Phase 7's is_emailable_identity getattr + the C5 tripwire assume). Set
    # atomically at INSERT time by the agent-company-resolution sweep; NULL for
    # every human-resolved row. Any row carrying this can NEVER be an outreach
    # target (SPEC AC10).
    source_agent_visit_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Ingest abuse marker, copied from Visitor.is_abuse_flagged inside the SAME
    # atomic INSERT that creates this row (_save_identified). Any row carrying it
    # can NEVER be an outreach target — see is_emailable_identity.
    is_abuse_flagged: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    # Cadence bot flag (visibility-only, see cadence_bot_flag.py) — structurally
    # independent of is_abuse_flagged; never read by is_emailable_identity();
    # never excluded from any aggregate FILTER clause. Mirrored from
    # Visitor.is_bot_suspect by the batch sweep. A flagged row stays fully
    # emailable and fully counted — the flag is a dashboard badge, nothing more.
    is_bot_suspect: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    # Outlier / internal-traffic damping — mirrored from Visitor.is_internal_suspect
    # by the batch sweep (and by the manual-override endpoint). NOT sticky: unlike
    # is_abuse_flagged above, this column is cleared as well as set, because the
    # signal must be fully reversible. Never read by is_emailable_identity() — a
    # flagged row stays exactly as emailable as any other.
    is_internal_suspect: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    # Phase 05 (encrypt PII at rest) — added nullable, not yet read/written.
    email_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_bidx: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    full_name_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ResolutionLog(Base):
    __tablename__ = "resolution_logs"
    __table_args__ = (
        Index("idx_resolution_logs_site_created", "site_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[str] = mapped_column(String(50), nullable=False)
    visitor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    success: Mapped[bool] = mapped_column(nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    response_time_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# Resolution-eligibility floor ONLY. The "hot / high-intent" DISPLAY label used by
# kpi.py / hot_alert.py / conviction.py / timeseries.py stays at 40 — do not couple them.
RESOLUTION_MIN_INTENT = 20


def resolution_intent_filter(all_us_site_ids=(), no_floor_site_ids=()):
    """Resolution-eligibility intent gate.

    Three tiers, widest first:

    - Sites listed in ``no_floor_site_ids`` are inside the first-win boost window
      (fewer than ``settings.first_win_boost_count`` identified visitors ever, see
      ``services.resolution_eligibility.first_win_boost_site_ids``): the intent floor
      is waived entirely, so every anonymous visitor qualifies.
    - Sites listed in ``all_us_site_ids`` (the owner's own domains) qualify every US
      visitor at any intent_score.
    - Everything else keeps intent_score >= RESOLUTION_MIN_INTENT (20) so provider
      budgets aren't burned on low-intent traffic.

    Both arguments default to empty, which reduces to the plain floor.
    """
    base = Visitor.intent_score >= RESOLUTION_MIN_INTENT
    ids = [s for s in all_us_site_ids if s]
    no_floor_ids = [s for s in no_floor_site_ids if s]
    if ids:
        base = or_(
            and_(
                Visitor.site_id.in_(ids),
                func.upper(Visitor.country_code) == "US",
            ),
            base,
        )
    if not no_floor_ids:
        return base
    return or_(Visitor.site_id.in_(no_floor_ids), base)
