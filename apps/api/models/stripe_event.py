"""Processed Stripe webhook event ids — idempotency ledger.

Stripe delivers webhooks at-least-once and out of order. Inserting the event
id here (primary key) before processing makes redelivered events no-ops: the
duplicate insert violates the PK and the handler returns early.
"""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class StripeEvent(Base):
    __tablename__ = "stripe_events"

    # Stripe event ids ("evt_...") are globally unique.
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
