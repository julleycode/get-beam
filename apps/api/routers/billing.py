"""Billing router — Lemon Squeezy Checkout, Portal, status, and webhook.

Lemon Squeezy is the active billing provider (Merchant of Record). Stripe is
unavailable in Vietnam, so the stripe_* settings are dormant. The existing
`stripe_customer_id` / `stripe_subscription_id` columns are reused to store the
Lemon Squeezy customer id / subscription id — no DB migration required.
"""

import hashlib
import hmac
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.dependencies import get_current_user
from apps.api.models.database import get_db
from apps.api.models.user import User
from apps.api.services.billing import get_plan_limits

logger = structlog.get_logger()

router = APIRouter()

_LS_API = "https://api.lemonsqueezy.com/v1"

# Lemon Squeezy subscription statuses that still grant plan access. "cancelled"
# stays entitled until the period ends (LS keeps it active until ends_at);
# "expired"/"unpaid"/"paused" lose access and fall back to free.
_ENTITLED_STATUSES = {"active", "on_trial", "past_due", "cancelled"}


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

def _resolve_variant_id(plan: str, interval: str) -> str:
    """Map (plan, interval) to the configured Lemon Squeezy variant id."""
    mapping = {
        ("pro", "monthly"): settings.ls_variant_pro_monthly,
        ("pro", "yearly"): settings.ls_variant_pro_yearly,
        ("max", "monthly"): settings.ls_variant_max_monthly,
        ("max", "yearly"): settings.ls_variant_max_yearly,
    }
    variant_id = mapping.get((plan, interval))
    if not variant_id:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown plan/interval combination: {plan}/{interval}",
        )
    return variant_id


def _variant_to_plan(variant_id: str) -> str:
    """Reverse-map a Lemon Squeezy variant id to an internal plan name."""
    mapping = {
        str(settings.ls_variant_pro_monthly): "pro",
        str(settings.ls_variant_pro_yearly): "pro",
        str(settings.ls_variant_max_monthly): "max",
        str(settings.ls_variant_max_yearly): "max",
    }
    return mapping.get(str(variant_id), "free")


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    """Parse a Lemon Squeezy ISO-8601 timestamp (may end in 'Z')."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


async def _ls_request(method: str, path: str, json_body: Optional[dict] = None) -> dict:
    """Call the Lemon Squeezy API with timeout + retry on network/5xx errors."""
    if not settings.lemonsqueezy_api_key:
        raise HTTPException(status_code=503, detail="Billing is not configured")

    headers = {
        "Authorization": f"Bearer {settings.lemonsqueezy_api_key}",
        "Accept": "application/vnd.api+json",
        "Content-Type": "application/vnd.api+json",
    }
    last_error: Optional[Exception] = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.request(
                    method, f"{_LS_API}{path}", headers=headers, json=json_body
                )
            if resp.status_code >= 500:
                last_error = httpx.HTTPStatusError(
                    "server error", request=resp.request, response=resp
                )
                continue  # retry transient server errors
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            # 4xx is a caller/config error — surface, don't retry.
            logger.error(
                "lemonsqueezy_api_error",
                path=path,
                status=exc.response.status_code,
                body=exc.response.text[:500],
            )
            raise HTTPException(status_code=502, detail="Billing provider error")
        except httpx.RequestError as exc:
            last_error = exc  # network error — retry

    logger.error("lemonsqueezy_unreachable", path=path, error=str(last_error))
    raise HTTPException(status_code=502, detail="Billing provider unreachable")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout_session(
    body: CheckoutRequest,
    user: User = Depends(get_current_user),
) -> CheckoutResponse:
    """Create a Lemon Squeezy checkout and return the redirect URL."""
    if body.plan not in ("pro", "max"):
        raise HTTPException(status_code=400, detail="plan must be 'pro' or 'max'")
    if body.interval not in ("monthly", "yearly"):
        raise HTTPException(status_code=400, detail="interval must be 'monthly' or 'yearly'")

    variant_id = _resolve_variant_id(body.plan, body.interval)

    payload = {
        "data": {
            "type": "checkouts",
            "attributes": {
                "checkout_data": {
                    "email": user.email,
                    "name": user.full_name or "",
                    # Carried back on every webhook as meta.custom_data.user_id.
                    "custom": {"user_id": str(user.id)},
                },
                "product_options": {
                    "redirect_url": f"{settings.frontend_url}/dashboard/billing?success=1",
                },
            },
            "relationships": {
                "store": {
                    "data": {"type": "stores", "id": str(settings.lemonsqueezy_store_id)}
                },
                "variant": {
                    "data": {"type": "variants", "id": str(variant_id)}
                },
            },
        }
    }
    resp = await _ls_request("POST", "/checkouts", payload)
    checkout_url = resp.get("data", {}).get("attributes", {}).get("url")
    if not checkout_url:
        logger.error("lemonsqueezy_checkout_no_url", response=str(resp)[:500])
        raise HTTPException(status_code=502, detail="Checkout creation failed")

    logger.info("lemonsqueezy_checkout_created", user_id=str(user.id), plan=body.plan)
    return CheckoutResponse(checkout_url=checkout_url)


@router.post("/portal", response_model=PortalResponse)
async def create_portal_session(
    user: User = Depends(get_current_user),
) -> PortalResponse:
    """Return the Lemon Squeezy customer portal URL for the user's subscription."""
    if not user.stripe_subscription_id:
        raise HTTPException(
            status_code=400,
            detail="No billing account found. Subscribe to a plan first.",
        )

    resp = await _ls_request("GET", f"/subscriptions/{user.stripe_subscription_id}")
    urls = resp.get("data", {}).get("attributes", {}).get("urls", {}) or {}
    portal_url = urls.get("customer_portal")
    if not portal_url:
        logger.error("lemonsqueezy_portal_no_url", user_id=str(user.id))
        raise HTTPException(status_code=502, detail="Portal URL unavailable")

    logger.info("lemonsqueezy_portal_created", user_id=str(user.id))
    return PortalResponse(portal_url=portal_url)


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
async def lemonsqueezy_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
    x_event_name: Optional[str] = Header(None, alias="X-Event-Name"),
) -> dict:
    """Lemon Squeezy webhook — NO auth. Verified via X-Signature HMAC-SHA256.

    Handlers set absolute state from the payload, so at-least-once redelivery is
    naturally idempotent (no event-id table needed).
    """
    payload = await request.body()

    if not settings.lemonsqueezy_webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook not configured")
    if not x_signature:
        raise HTTPException(status_code=400, detail="Missing X-Signature header")

    expected = hmac.new(
        settings.lemonsqueezy_webhook_secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, x_signature):
        logger.warning("lemonsqueezy_webhook_invalid_signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        event = await request.json()
    except Exception as exc:  # noqa: BLE001
        logger.error("lemonsqueezy_webhook_parse_error", error=str(exc))
        raise HTTPException(status_code=400, detail="Webhook parse error")

    meta: dict = event.get("meta", {}) or {}
    data: dict = event.get("data", {}) or {}
    event_name: str = x_event_name or meta.get("event_name", "")
    logger.info("lemonsqueezy_webhook_received", event_name=event_name)

    if event_name in (
        "subscription_created",
        "subscription_updated",
        "subscription_cancelled",
        "subscription_expired",
    ):
        await _apply_subscription(data, meta, db)
    elif event_name == "subscription_payment_failed":
        await _handle_payment_failed(data, meta, db)
    else:
        logger.debug("lemonsqueezy_webhook_unhandled", event_name=event_name)

    return {"received": True}


# ── Webhook handlers ────────────────────────────────────────────────────────────

async def _find_user(meta: dict, attrs: dict, db: AsyncSession) -> Optional[User]:
    """Locate the user from webhook custom_data.user_id, falling back to the
    stored Lemon Squeezy customer id."""
    custom: dict = meta.get("custom_data", {}) or {}
    user_id_str = custom.get("user_id")
    if user_id_str:
        try:
            result = await db.execute(
                select(User).where(User.id == uuid.UUID(str(user_id_str)))
            )
            user = result.scalar_one_or_none()
            if user is not None:
                return user
        except ValueError:
            pass

    customer_id = str(attrs.get("customer_id") or "")
    if customer_id:
        result = await db.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )
        return result.scalar_one_or_none()
    return None


async def _apply_subscription(data: dict, meta: dict, db: AsyncSession) -> None:
    """Sync plan, status, customer/subscription ids, and renewal date from a
    Lemon Squeezy subscription object."""
    attrs: dict = data.get("attributes", {}) or {}
    subscription_id = str(data.get("id") or "")

    user = await _find_user(meta, attrs, db)
    if user is None:
        logger.warning(
            "lemonsqueezy_subscription_user_not_found",
            subscription_id=subscription_id,
            customer_id=attrs.get("customer_id"),
        )
        return

    status: str = attrs.get("status", "")
    variant_id = str(attrs.get("variant_id") or "")
    plan = _variant_to_plan(variant_id) if status in _ENTITLED_STATUSES else "free"

    values: dict = {
        "stripe_subscription_id": subscription_id or user.stripe_subscription_id,
        "subscription_status": status,
        "plan": plan,
        "current_period_end": _parse_dt(attrs.get("renews_at")),
        "trial_ends_at": _parse_dt(attrs.get("trial_ends_at")),
    }
    customer_id = str(attrs.get("customer_id") or "")
    if customer_id:
        values["stripe_customer_id"] = customer_id

    await db.execute(update(User).where(User.id == user.id).values(**values))
    await db.commit()
    logger.info(
        "lemonsqueezy_subscription_synced",
        user_id=str(user.id),
        plan=plan,
        status=status,
    )


async def _handle_payment_failed(data: dict, meta: dict, db: AsyncSession) -> None:
    """Mark subscription past_due on a failed renewal payment (keeps plan during
    the dunning grace period)."""
    attrs: dict = data.get("attributes", {}) or {}
    user = await _find_user(meta, attrs, db)
    if user is None:
        logger.warning("lemonsqueezy_payment_failed_user_not_found")
        return

    await db.execute(
        update(User).where(User.id == user.id).values(subscription_status="past_due")
    )
    await db.commit()
    logger.warning("lemonsqueezy_payment_failed", user_id=str(user.id))
