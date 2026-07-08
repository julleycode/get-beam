"""Billing router — Gumroad checkout/management, status, and webhooks.

Gumroad is the active billing provider (Merchant of Record). Stripe is
unavailable in Vietnam, and Lemon Squeezy rejected Beam's category. The existing
`stripe_customer_id` / `stripe_subscription_id` columns are reused to store
provider customer/subscription ids — no DB migration required.
"""

import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.dependencies import get_current_user
from apps.api.models.database import get_db
from apps.api.models.user import User
from apps.api.services.billing import check_usage_allowed, get_effective_limit

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


class CancelRequest(BaseModel):
    reason: Optional[str] = None


class CancelResponse(BaseModel):
    subscription_status: Optional[str]
    current_period_end: Optional[datetime]
    portal_url: Optional[str] = None
    message: Optional[str] = None


class BillingStatusResponse(BaseModel):
    plan: str
    subscription_status: Optional[str]
    monthly_identified_count: int
    monthly_limit: Optional[int]       # None = unlimited; includes referral bonus
    bonus_monthly_quota: int           # earned referral bonus baked into monthly_limit
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


def _append_query_params(url: str, params: dict[str, str]) -> str:
    """Merge query params into a URL without clobbering existing keys."""
    parsed = urlparse(url)
    merged = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in params.items():
        if value:
            merged[key] = value
    return urlunparse(parsed._replace(query=urlencode(merged)))


def _gumroad_checkout_base_url(plan: str, interval: str) -> str:
    """Resolve the configured Gumroad checkout URL for a plan/interval."""
    mapping = {
        ("pro", "monthly"): settings.gumroad_checkout_pro_monthly_url,
        ("pro", "yearly"): settings.gumroad_checkout_pro_yearly_url,
        ("max", "monthly"): settings.gumroad_checkout_max_monthly_url,
        ("max", "yearly"): settings.gumroad_checkout_max_yearly_url,
    }
    configured = (mapping.get((plan, interval)) or "").strip()
    if configured:
        return configured

    permalink = (settings.gumroad_product_permalink or "").strip()
    if permalink:
        # Fallback to the shared product page when per-tier deep links are not
        # configured yet. The buyer can still choose the desired variant there.
        return f"https://gumroad.com/l/{permalink}"

    raise HTTPException(status_code=503, detail="Gumroad checkout is not configured")


def _gumroad_management_url(user: User) -> str:
    """URL the customer can use to manage or cancel their Gumroad subscription."""
    configured = (settings.gumroad_customer_portal_url or "").strip()
    if configured:
        return configured

    return "https://gumroad.com/library"


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
    """Return a Gumroad checkout URL for the selected Beam plan."""
    if body.plan not in ("pro", "max"):
        raise HTTPException(status_code=400, detail="plan must be 'pro' or 'max'")
    if body.interval not in ("monthly", "yearly"):
        raise HTTPException(status_code=400, detail="interval must be 'monthly' or 'yearly'")

    checkout_url = _append_query_params(
        _gumroad_checkout_base_url(body.plan, body.interval),
        {
            "wanted": "true",
            "email": user.email,
        },
    )

    logger.info(
        "gumroad_checkout_created",
        user_id=str(user.id),
        plan=body.plan,
        interval=body.interval,
    )
    return CheckoutResponse(checkout_url=checkout_url)


@router.post("/portal", response_model=PortalResponse)
async def create_portal_session(
    user: User = Depends(get_current_user),
) -> PortalResponse:
    """Return the Gumroad management URL for the user's subscription."""
    if not user.stripe_subscription_id:
        raise HTTPException(
            status_code=400,
            detail="No billing account found. Subscribe to a plan first.",
        )
    portal_url = _gumroad_management_url(user)
    logger.info("gumroad_portal_created", user_id=str(user.id))
    return PortalResponse(portal_url=portal_url)


@router.post("/cancel", response_model=CancelResponse)
async def cancel_subscription(
    body: CancelRequest,
    user: User = Depends(get_current_user),
) -> CancelResponse:
    """Send the user to Gumroad to cancel or manage their paid plan.

    Gumroad subscription cancellation must be completed by the buyer inside
    Gumroad. The webhook remains authoritative and marks the subscription as
    cancelled once Gumroad emits the lifecycle ping.
    """
    if not user.stripe_subscription_id:
        raise HTTPException(status_code=400, detail="No active paid plan to cancel.")

    reason = body.reason.strip()[:1000] if body.reason else None
    logger.info(
        "subscription_cancel_requested", user_id=str(user.id), reason=reason
    )
    portal_url = _gumroad_management_url(user)
    logger.info(
        "gumroad_cancel_redirect_created",
        user_id=str(user.id),
    )
    return CancelResponse(
        subscription_status=user.subscription_status,
        current_period_end=user.current_period_end,
        portal_url=portal_url,
        message="Open Gumroad to cancel or manage this subscription.",
    )


@router.get("/status", response_model=BillingStatusResponse)
async def get_billing_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BillingStatusResponse:
    """Return the current user's plan, usage count, and limits.

    Also runs the lazy monthly reset so dashboard UI stays in sync with the same
    quota logic the resolver enforces.
    """
    await check_usage_allowed(db, str(user.id))
    await db.refresh(user)
    return BillingStatusResponse(
        plan=user.plan,
        subscription_status=user.subscription_status,
        monthly_identified_count=user.monthly_identified_count,
        # Effective limit (plan + referral bonus) so the sidebar badge and the
        # billing page show the same number check_usage_allowed enforces.
        monthly_limit=get_effective_limit(user.plan, user.bonus_monthly_quota),
        bonus_monthly_quota=user.bonus_monthly_quota,
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


# ── Gumroad webhook (fallback Merchant of Record) ───────────────────────────────
# Lemon Squeezy rejected Beam's product category, so Gumroad is the live MoR.
# Gumroad gives NO HMAC signature: the Ping is form-encoded and authenticated by
# a secret token in the URL (?token=...) plus an optional seller_id check. State
# is set absolutely, so redelivery and recurring-charge Pings are idempotent.

# Gumroad recurrence -> entitlement window (days). One day of slack so access
# never lapses before the next recurring-charge Ping refreshes the period.
_GUMROAD_PERIOD_DAYS = {
    "monthly": 31,
    "quarterly": 93,
    "biannually": 186,
    "yearly": 366,
    "every_two_years": 731,
}

def _gumroad_tier_to_plan(tier_name: str, price_cents: int) -> str:
    """Map a Gumroad membership tier (variant) to an internal plan name.

    Prefer the tier name ("Pro"/"Max"); fall back to the amount paid so a renamed
    tier still resolves. Unknown -> "free" (grant nothing)."""
    name = (tier_name or "").strip().lower()
    if "max" in name:
        return "max"
    if "pro" in name:
        return "pro"
    if price_cents in (4900, 46800):   # Max monthly / yearly
        return "max"
    if price_cents in (1900, 18000):   # Pro monthly / yearly
        return "pro"
    return "free"


def _gumroad_extract_tier(form) -> str:
    """Read the tier/variant name from a Gumroad Ping. Tiered memberships send it
    as a bracketed key, e.g. ``variants[Tier]=Pro``."""
    for key, value in form.items():
        if key.startswith("variants[") or key == "tier_name":
            return str(value)
    return ""


def _gumroad_period_end(start: datetime, recurrence: str) -> datetime:
    days = _GUMROAD_PERIOD_DAYS.get((recurrence or "").strip().lower(), 31)
    return start + timedelta(days=days)


def _to_cents(value: Optional[str]) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


async def _gumroad_find_user(
    email: str, subscription_id: str, db: AsyncSession
) -> Optional[User]:
    """Find the user by Gumroad subscription id (set on a prior Ping) or by email
    (case-insensitive)."""
    if subscription_id:
        result = await db.execute(
            select(User).where(User.stripe_subscription_id == subscription_id)
        )
        user = result.scalar_one_or_none()
        if user is not None:
            return user
    if email:
        result = await db.execute(
            select(User).where(func.lower(User.email) == email)
        )
        return result.scalar_one_or_none()
    return None


@router.post("/gumroad/webhook")
async def gumroad_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Gumroad Ping — auto-provisions a Beam plan on subscription sales.

    Auth: Gumroad has no signature, so we require a secret token in the URL
    (``?token=<gumroad_webhook_secret>``) and, when configured, a matching
    seller_id. A sale for an email with no account yet creates a minimal user
    row; when that buyer later signs in with the same email, Clerk links to this
    row (see dependencies.get_current_user) so the plan is preserved.

    Events: the plain Settings Ping fires on the `sale` resource only (initial +
    recurring charges) — those ACTIVATE. refund / dispute / cancellation /
    subscription_ended reach this endpoint only when registered as Gumroad
    resource_subscriptions (PUT /v2/resource_subscriptions) pointing at this same
    URL with the ?token= query preserved; those REVOKE (hard) or mark cancelled
    (soft, keep access until the period ends).
    """
    if not settings.gumroad_webhook_secret:
        raise HTTPException(status_code=503, detail="Gumroad webhook not configured")

    form = await request.form()
    token = request.query_params.get("token") or str(form.get("token") or "")
    if not hmac.compare_digest(token, settings.gumroad_webhook_secret):
        logger.warning("gumroad_webhook_invalid_token")
        raise HTTPException(status_code=401, detail="Invalid token")

    if settings.gumroad_seller_id and str(form.get("seller_id") or "") != str(
        settings.gumroad_seller_id
    ):
        logger.warning("gumroad_webhook_seller_mismatch")
        raise HTTPException(status_code=400, detail="Unexpected seller")

    # Gumroad uses `email` on purchase pings (sale/refund/dispute) but
    # `user_email` on subscription-lifecycle pings (cancellation/subscription_ended)
    # — read both. subscription_id is the stable key across every event.
    email = str(form.get("email") or form.get("user_email") or "").strip().lower()
    subscription_id = str(form.get("subscription_id") or "")

    # A test ping (or a Gumroad test-mode purchase) must never mutate a real
    # account. Live sales omit `test` or send it false.
    if str(form.get("test") or "").lower() == "true":
        logger.info("gumroad_webhook_test_ping_ignored", subscription_id=subscription_id)
        return {"received": True}

    refunded = str(form.get("refunded") or "").lower() == "true"
    disputed = str(form.get("disputed") or "").lower() == "true"
    dispute_won = str(form.get("dispute_won") or "").lower() == "true"
    cancelled = str(form.get("cancelled") or "").lower() == "true"
    ended = bool(form.get("ended_reason")) or bool(form.get("ended_at"))

    # HARD revoke → access ends NOW: money returned (refund), a live chargeback
    # (dispute that was NOT won/reversed), or the subscription actually ended.
    hard_revoke = refunded or (disputed and not dispute_won) or ended
    # SOFT cancel → the buyer cancelled but keeps access until the paid period
    # ends (mirrors Lemon Squeezy: "cancelled" stays entitled until renews_at).
    soft_cancel = cancelled and not hard_revoke

    logger.info(
        "gumroad_webhook_received",
        has_email=bool(email),
        subscription_id=subscription_id,
        hard_revoke=hard_revoke,
        soft_cancel=soft_cancel,
    )

    # ── Hard revoke: refund / live dispute / subscription ended → drop to free ──
    if hard_revoke:
        user = await _gumroad_find_user(email, subscription_id, db)
        if user is None:
            logger.warning(
                "gumroad_revoke_user_not_found", subscription_id=subscription_id
            )
            return {"received": True}
        status = "refunded" if refunded else ("disputed" if disputed else "ended")
        await db.execute(
            update(User)
            .where(User.id == user.id)
            .values(plan="free", subscription_status=status)
        )
        await db.commit()
        logger.info("gumroad_subscription_revoked", user_id=str(user.id), status=status)
        return {"received": True}

    # ── Soft cancel: keep the plan until the paid period ends ──
    if soft_cancel:
        user = await _gumroad_find_user(email, subscription_id, db)
        if user is None:
            logger.warning(
                "gumroad_cancel_user_not_found", subscription_id=subscription_id
            )
            return {"received": True}
        values: dict = {"subscription_status": "cancelled"}
        period_end = _parse_dt(form.get("cancelled_at"))
        if period_end is not None:
            values["current_period_end"] = period_end
        await db.execute(update(User).where(User.id == user.id).values(**values))
        await db.commit()
        logger.info("gumroad_subscription_cancelled_pending_end", user_id=str(user.id))
        return {"received": True}

    # ── Activation: a sale or recurring charge ──
    if not email:
        logger.warning("gumroad_webhook_no_email")
        return {"received": True}

    plan = _gumroad_tier_to_plan(_gumroad_extract_tier(form), _to_cents(form.get("price")))
    if plan == "free":
        logger.warning("gumroad_webhook_unmapped_tier", subscription_id=subscription_id)
        return {"received": True}

    start = _parse_dt(form.get("sale_timestamp")) or datetime.now(timezone.utc)
    period_end = _gumroad_period_end(start, str(form.get("recurrence") or ""))

    user = await _gumroad_find_user(email, subscription_id, db)
    if user is None:
        user = User(
            email=email,
            plan=plan,
            subscription_status="active",
            current_period_end=period_end,
            stripe_subscription_id=subscription_id or None,
        )
        db.add(user)
        await db.commit()
        logger.info(
            "gumroad_subscription_provisioned", user_id=str(user.id), plan=plan, new_user=True
        )
        return {"received": True}

    values: dict = {
        "plan": plan,
        "subscription_status": "active",
        "current_period_end": period_end,
    }
    if subscription_id:
        values["stripe_subscription_id"] = subscription_id
    await db.execute(update(User).where(User.id == user.id).values(**values))
    await db.commit()
    logger.info("gumroad_subscription_synced", user_id=str(user.id), plan=plan)
    return {"received": True}
