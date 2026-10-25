"""x402 paid-request ledger (InFlow x402 seller, /api/v1/paid/*).

One row per distinct x402 payment payload presented to a paid route. Serves two
jobs:

1. Idempotency / replay: ``payment_hash`` (sha256 of the canonical decoded
   payment payload) is UNIQUE. A request whose payload already settled gets the
   cached response back and the upstream handler is NOT called again — the buyer
   is never charged twice and Beam never pays a provider twice for one payment.
   A concurrent duplicate while the first is still ``pending`` gets 409.
2. Reconciliation: route, amount (atomic units), asset, network, payer and the
   facilitator's settle transaction id, so the InFlow ledger can be matched.

Not tenant data: buyers are anonymous agents, there is no site/user here. The
cached ``response_body`` is the paid capability's output (company firmographics,
public posts, a draft, a platform guess) — no Beam visitor data.
"""

from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base

# pending -> settled | handler_failed | settle_failed. Failed rows may be
# re-claimed (back to pending) by a retry with the same payload.
PAID_REQUEST_STATUSES = ("pending", "settled", "handler_failed", "settle_failed")


class PaidRequest(Base):
    """``id``/``created_at``/``updated_at`` come from ``Base``."""

    __tablename__ = "paid_requests"

    payment_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    route_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    scheme: Mapped[str | None] = mapped_column(String(32), nullable=True)
    network: Mapped[str | None] = mapped_column(String(64), nullable=True)
    asset: Mapped[str | None] = mapped_column(String(128), nullable=True)
    amount: Mapped[str | None] = mapped_column(String(80), nullable=True)
    payer: Mapped[str | None] = mapped_column(String(256), nullable=True)
    transaction: Mapped[str | None] = mapped_column(String(256), nullable=True)
    error_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    payment_response_header: Mapped[str | None] = mapped_column(Text, nullable=True)
