"""Billing router — Stripe Checkout, Portal, status, and webhook endpoints."""

import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.dependencies import get_current_user
from apps.api.models.database import get_db
from apps.api.models.user import User
from apps.api.services.billing import PLAN_LIMITS, get_plan_limits

logger = structlog.get_logger()

router = APIRouter()


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    plan: str           # "pro" or "max"
    interval: str       # "monthly" or "yearly"


class CheckoutResponse(BaseModel):
    checkout_url: str


class PortalResponse(BaseModel):
    portal_url: str


class BillingStatusResponse(BaseModel):
    plan: str
    subscription_status: Optional[str]
    monthly_identified_count: int
    monthly_limit: Optional[int]       # None = unlimited
    trial_ends_at: Optional[datetime]
    current_period_end: Optional[datetime]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_price_id(plan: str, interval: str) -> str:
    """Map (plan, interval) to the configured Stripe Price ID."""
    mapping = {
        ("pro", "monthly"): settings.stripe_price_pro_monthly,
        ("pro", "yearly"): settings.stripe_price_pro_yearly,
        ("max", "monthly"): settings.stripe_price_max_monthly,
        ("max", "yearly"): settings.stripe_price_max_yearly,
    }
    price_id = mapping.get((plan, interval))
    if not price_id:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown plan/interval combination: {plan}/{interval}",
        )
    return price_id


async def _get_or_create_stripe_customer(user: User, db: AsyncSession) -> str:
    """Return existing Stripe customer ID or create a new one."""
    if user.stripe_customer_id:
        return user.stripe_customer_id

    import stripe  # lazy import — only needed when Stripe key is present

    stripe.api_key = settings.stripe_secret_key
    customer = stripe.Customer.create(
        email=user.email,
        name=user.full_name or "",
        metadata={"user_id": str(user.id)},
    )
    customer_id: str = customer["id"]

    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(stripe_customer_id=customer_id)
    )
    await db.commit()
    logger.info("stripe_customer_created", user_id=str(user.id), customer_id=customer_id)
    return customer_id


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout_session(
    body: CheckoutRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CheckoutResponse:
    """Create a Stripe Checkout Session and return the redirect URL."""
    if body.plan not in ("pro", "max"):
        raise HTTPException(status_code=400, detail="plan must be 'pro' or 'max'")
    if body.interval not in ("monthly", "yearly"):
        raise HTTPException(status_code=400, detail="interval must be 'monthly' or 'yearly'")

    if settings.mock_external_apis:
        mock_url = (
            f"https://mock-stripe.com/checkout"
            f"?plan={body.plan}&interval={body.interval}&session={uuid.uuid4().hex}"
        )
        logger.info("stripe_checkout_mock", user_id=str(user.id), plan=body.plan)
        return CheckoutResponse(checkout_url=mock_url)

    price_id = _resolve_price_id(body.plan, body.interval)

    import stripe

    stripe.api_key = settings.stripe_secret_key
    customer_id = await _get_or_create_stripe_customer(user, db)

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{settings.frontend_url}/dashboard/billing?success=1",
        cancel_url=f"{settings.frontend_url}/dashboard/billing?canceled=1",
        metadata={"user_id": str(user.id)},
    )
    logger.info(
        "stripe_checkout_created",
        user_id=str(user.id),
        session_id=session["id"],
        plan=body.plan,
    )
    return CheckoutResponse(checkout_url=session["url"])


@router.post("/portal", response_model=PortalResponse)
async def create_portal_session(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PortalResponse:
    """Create a Stripe Customer Portal session and return the redirect URL."""
    if settings.mock_external_apis:
        mock_url = f"https://mock-stripe.com/portal?session={uuid.uuid4().hex}"
        logger.info("stripe_portal_mock", user_id=str(user.id))
        return PortalResponse(portal_url=mock_url)

    if not user.stripe_customer_id:
        raise HTTPException(
            status_code=400,
            detail="No billing account found. Subscribe to a plan first.",
        )

    import stripe

    stripe.api_key = settings.stripe_secret_key
    kwargs: dict = {
        "customer": user.stripe_customer_id,
        "return_url": f"{settings.frontend_url}/dashboard/billing",
    }
    if settings.stripe_portal_config_id:
        kwargs["configuration"] = settings.stripe_portal_config_id

    portal = stripe.billing_portal.Session.create(**kwargs)
    logger.info("stripe_portal_created", user_id=str(user.id))
    return PortalResponse(portal_url=portal["url"])


@router.get("/status", response_model=BillingStatusResponse)
async def get_billing_status(
    user: User = Depends(get_current_user),
) -> BillingStatusResponse:
    """Return the current user's plan, usage count, and limits."""
    return BillingStatusResponse(
        plan=user.plan,
        subscription_status=user.subscription_status,
        monthly_identified_count=user.monthly_identified_count,
        monthly_limit=get_plan_limits(user.plan),
        trial_ends_at=user.trial_ends_at,
        current_period_end=user.current_period_end,
    )


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    stripe_signature: Optional[str] = Header(None, alias="stripe-signature"),
) -> dict:
    """Stripe webhook — NO auth required. Verified via Stripe signature."""
    payload = await request.body()

    if settings.mock_external_apis:
        # In mock mode, accept raw JSON and process as-is for testing
        import json as _json

        try:
            event = _json.loads(payload)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON payload")
        logger.info("stripe_webhook_mock", event_type=event.get("type"))
        await _handle_webhook_event(event, db)
        return {"received": True}

    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")

    import stripe

    stripe.api_key = settings.stripe_secret_key
    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=stripe_signature,
            secret=settings.stripe_webhook_secret,
        )
    except stripe.error.SignatureVerificationError:
        logger.warning("stripe_webhook_invalid_signature")
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")
    except Exception as exc:
        logger.error("stripe_webhook_parse_error", error=str(exc))
        raise HTTPException(status_code=400, detail="Webhook parse error")

    logger.info("stripe_webhook_received", event_type=event["type"], event_id=event["id"])
    await _handle_webhook_event(event, db)
    return {"received": True}


async def _handle_webhook_event(event: dict, db: AsyncSession) -> None:
    """Dispatch Stripe webhook events to the appropriate handler."""
    event_type: str = event.get("type", "")
    data_object: dict = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        await _handle_checkout_completed(data_object, db)
    elif event_type == "customer.subscription.updated":
        await _handle_subscription_updated(data_object, db)
    elif event_type == "customer.subscription.deleted":
        await _handle_subscription_deleted(data_object, db)
    elif event_type == "invoice.payment_failed":
        await _handle_payment_failed(data_object, db)
    else:
        logger.debug("stripe_webhook_unhandled", event_type=event_type)


async def _user_by_customer_id(customer_id: str, db: AsyncSession) -> Optional[User]:
    result = await db.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )
    return result.scalar_one_or_none()


async def _handle_checkout_completed(obj: dict, db: AsyncSession) -> None:
    """Mark the user's subscription as active after successful checkout."""
    customer_id: str = obj.get("customer", "")
    subscription_id: str = obj.get("subscription", "")

    # Extract plan from metadata if present
    metadata: dict = obj.get("metadata", {})
    user_id_str: str = metadata.get("user_id", "")

    user: Optional[User] = None
    if user_id_str:
        try:
            uid = uuid.UUID(user_id_str)
            result = await db.execute(select(User).where(User.id == uid))
            user = result.scalar_one_or_none()
        except ValueError:
            pass

    if user is None and customer_id:
        user = await _user_by_customer_id(customer_id, db)

    if user is None:
        logger.warning("stripe_checkout_completed_user_not_found", customer_id=customer_id)
        return

    # Update subscription_id — plan will be set by subscription.updated event
    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(
            stripe_customer_id=customer_id,
            stripe_subscription_id=subscription_id,
            subscription_status="active",
        )
    )
    await db.commit()
    logger.info(
        "stripe_checkout_completed",
        user_id=str(user.id),
        subscription_id=subscription_id,
    )


async def _handle_subscription_updated(obj: dict, db: AsyncSession) -> None:
    """Sync plan, status, and billing period from Stripe subscription."""
    customer_id: str = obj.get("customer", "")
    subscription_id: str = obj.get("id", "")
    status: str = obj.get("status", "")
    current_period_end_ts: Optional[int] = obj.get("current_period_end")
    trial_end_ts: Optional[int] = obj.get("trial_end")

    # Derive plan from the first line item price
    plan = "free"
    items = obj.get("items", {}).get("data", [])
    if items:
        price_id: str = items[0].get("price", {}).get("id", "")
        plan = _price_id_to_plan(price_id)

    user = await _user_by_customer_id(customer_id, db)
    if user is None:
        logger.warning("stripe_subscription_updated_user_not_found", customer_id=customer_id)
        return

    values: dict = {
        "stripe_subscription_id": subscription_id,
        "subscription_status": status,
        "plan": plan,
    }
    if current_period_end_ts:
        values["current_period_end"] = datetime.fromtimestamp(
            current_period_end_ts, tz=timezone.utc
        )
    if trial_end_ts:
        values["trial_ends_at"] = datetime.fromtimestamp(trial_end_ts, tz=timezone.utc)

    await db.execute(update(User).where(User.id == user.id).values(**values))
    await db.commit()
    logger.info(
        "stripe_subscription_updated",
        user_id=str(user.id),
        plan=plan,
        status=status,
    )


async def _handle_subscription_deleted(obj: dict, db: AsyncSession) -> None:
    """Downgrade user to free plan when subscription is cancelled."""
    customer_id: str = obj.get("customer", "")
    user = await _user_by_customer_id(customer_id, db)
    if user is None:
        logger.warning("stripe_subscription_deleted_user_not_found", customer_id=customer_id)
        return

    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(
            plan="free",
            subscription_status="canceled",
            stripe_subscription_id=None,
            current_period_end=None,
        )
    )
    await db.commit()
    logger.info("stripe_subscription_deleted", user_id=str(user.id))


async def _handle_payment_failed(obj: dict, db: AsyncSession) -> None:
    """Mark subscription as past_due on payment failure."""
    customer_id: str = obj.get("customer", "")
    user = await _user_by_customer_id(customer_id, db)
    if user is None:
        logger.warning("stripe_payment_failed_user_not_found", customer_id=customer_id)
        return

    await db.execute(
        update(User)
        .where(User.id == user.id)
        .values(subscription_status="past_due")
    )
    await db.commit()
    logger.warning("stripe_payment_failed", user_id=str(user.id))


def _price_id_to_plan(price_id: str) -> str:
    """Reverse-map a Stripe Price ID to an internal plan name."""
    mapping = {
        settings.stripe_price_pro_monthly: "pro",
        settings.stripe_price_pro_yearly: "pro",
        settings.stripe_price_max_monthly: "max",
        settings.stripe_price_max_yearly: "max",
    }
    return mapping.get(price_id, "free")
