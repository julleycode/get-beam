"""Captured HTTP request/response pair for the admin debug log viewer.

One row per request the middleware decided was worth keeping — by default only
requests that were DROPPED or FLAGGED (see ``services/request_logger.py`` for the
decision), never the whole traffic stream.

Structurally an operator/debug artifact, NOT product data:
  - never joined to ``Visitor`` / ``IdentifiedVisitor`` / ``Event``
  - never read by ``is_emailable_identity`` or any outreach path
  - admin-gated at the router, purged on a tighter window than raw events

Bodies are stored post-redaction (``services/log_redaction.py``): emails are
domain-only and credential-shaped keys are ``***``. Nothing writes a raw body
here.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import String, DateTime, Integer, Float, Boolean, Index, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class RequestLog(Base):
    """A single captured request/response pair."""

    __tablename__ = "request_logs"
    __table_args__ = (
        # The viewer's default query: newest first, optionally narrowed by
        # reason or site. created_at leads because every query is time-ordered.
        Index("idx_request_logs_created", "created_at"),
        Index("idx_request_logs_reason_created", "reason", "created_at"),
        Index("idx_request_logs_site_created", "site_id", "created_at"),
        Index("idx_request_logs_status_created", "status_code", "created_at"),
    )

    # ── What was called ──
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    query_params: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # ── What happened ──
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Why this row was kept: "http_error" | "bot_drop" | "abuse_flag" |
    # "rate_limited" | "exception" | "sampled". Indexed — it is the viewer's
    # primary facet.
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    # Free-text elaboration on `reason` (e.g. the UA pattern that matched).
    # Nullable: most rows need no elaboration beyond the reason code.
    reason_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Who called ──
    site_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── The payloads (already redacted) ──
    # JSONB when the body parsed as JSON. A non-JSON or oversized body is stored
    # as {"__raw__": "..."} so the column type stays uniform and the viewer
    # renders one shape.
    request_headers: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    request_body: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB, nullable=True)
    response_body: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(JSONB, nullable=True)
    # True when either body hit request_log_max_body_bytes and was cut short —
    # surfaced in the UI so an empty-looking payload is never mistaken for the
    # real thing.
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<RequestLog {self.method} {self.path} {self.status_code} ({self.reason})>"
