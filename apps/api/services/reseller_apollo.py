"""Paid Apollo person enrichment via a reseller (Locus) — the Buyer side of the
InFlow integration (INFLOW-INTEGRATION-PLAN.md task 70).

apps/api never touches payments. It asks apps/web's internal route
``POST {beam_web_internal_base}/api/internal/buy/apollo-person`` (shared secret
``X-Beam-Internal-Secret``) to buy one enrichment; apps/web pays with its InFlow
buyer key over x402 or MPP, enforcing a per-call price cap.

Money safety, enforced here:
- Gated: ``reseller_apollo_enabled`` AND no direct ``apollo_api_key``.
- A daily USD budget is RESERVED in Redis before every call (integer
  micro-dollars, atomic INCRBY); over budget or Redis down => no call.
- Exactly one POST, never retried (a retry could pay twice).
- After the call the reservation is reconciled: released when nothing was
  paid, trimmed to the real price on success, KEPT in full when the outcome is
  ambiguous (timeout, paid=null).
- Outbound body is the email only; the web route forces reveal_* = false.
- Logs carry status/outcome only — never the email or response body.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal

import httpx
import structlog

from apps.api.config import settings
from apps.api.services.redis_client import get_redis
from apps.api.services.usage_logger import log_api_call

logger = structlog.get_logger()

PROVIDER = "locus_apollo"
BUY_PATH = "/api/internal/buy/apollo-person"
CALL_TIMEOUT_SECONDS = 30.0
_MICROS = 1_000_000
_SPEND_KEY_TTL_SECONDS = 2 * 86400

# 402 errors from the web route that guarantee no payment was made.
_NOT_PAID_402 = {"price_above_cap", "no_payable_offer", "payment_pending_or_declined"}

Outcome = Literal["match", "no_match", "skipped", "failed"]


@dataclass(frozen=True)
class ResellerResult:
    """``match``/``no_match`` are definitive answers (cacheable); ``skipped``
    means no call was made; ``failed`` means try again another time."""

    outcome: Outcome
    data: dict | None = None
    amount_usd: float = 0.0
    paid: bool | None = False
    meta: dict = field(default_factory=dict)


def _usd_to_micros(value: float | Decimal) -> int:
    return int((Decimal(str(value)) * _MICROS).to_integral_value())


def spend_key(now: datetime | None = None) -> str:
    day = (now or datetime.now(timezone.utc)).strftime("%Y%m%d")
    return f"reseller:apollo:spend:{day}"


def reseller_gates_open() -> bool:
    """Flag on AND no direct Apollo key (the reseller is a fallback only)."""
    return bool(settings.reseller_apollo_enabled) and not settings.apollo_api_key


async def reserve_budget(key: str, micros: int) -> bool:
    """Atomically reserve ``micros`` under today's cap. Fail CLOSED on any error."""
    cap = _usd_to_micros(settings.reseller_daily_budget_usd)
    if micros <= 0 or cap <= 0:
        return False
    try:
        redis = get_redis()
        total = int(await redis.incrby(key, micros))
        if total == micros:
            await redis.expire(key, _SPEND_KEY_TTL_SECONDS)
        if total > cap:
            await redis.decrby(key, micros)
            logger.info("reseller_apollo_budget_exhausted")
            return False
        return True
    except Exception as exc:
        logger.warning("reseller_apollo_budget_unavailable", error=type(exc).__name__)
        return False


async def release_budget(key: str, micros: int) -> None:
    if micros <= 0:
        return
    try:
        await get_redis().decrby(key, micros)
    except Exception as exc:
        # Leaves the reservation in place: errs toward spending LESS.
        logger.warning("reseller_apollo_budget_release_failed", error=type(exc).__name__)


def _parse_amount(raw: object) -> Decimal | None:
    if not isinstance(raw, (str, int, float)):
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    return value if value >= 0 else None


def _person_from(data: object) -> dict | None:
    """Locus returns Apollo's people/match body ({"person": {...}}) — shape
    taken from the Locus listing, not yet seen on a paid response."""
    if isinstance(data, dict):
        person = data.get("person")
        if isinstance(person, dict) and person:
            return person
    return None


def _result_from_person(person: dict | None, amount: Decimal, paid: bool | None, meta: dict) -> ResellerResult:
    # Imported lazily: enricher imports this module.
    from apps.api.services.enricher import apollo_person_usable, map_apollo_person

    if person is None:
        return ResellerResult("no_match", None, float(amount), paid, meta)
    mapped = map_apollo_person(person)
    if not apollo_person_usable(mapped):
        logger.warning("reseller_apollo_unmapped_response", person_keys=sorted(person.keys())[:25])
        return ResellerResult("failed", None, float(amount), paid, meta)
    return ResellerResult("match", mapped, float(amount), paid, meta)


def _mock_result(email: str) -> ResellerResult:
    domain = email.rsplit("@", 1)[-1].lower()
    data = {
        "job_title": "Mock Title",
        "company_name": f"Mock Co ({domain})",
        "company_domain": domain,
        "seniority_level": "manager",
    }
    return ResellerResult("match", data, 0.0, False, {"mock": True})


async def purchase_apollo_person(
    email: str, *, site_id: str | None = None, visitor_id: str | None = None
) -> ResellerResult:
    """Buy one Apollo person enrichment for ``email`` through apps/web."""
    if not email or "@" not in email:
        return ResellerResult("skipped")
    if not reseller_gates_open():
        return ResellerResult("skipped")
    if settings.mock_external_apis:
        return _mock_result(email)

    base = (settings.beam_web_internal_base or "").strip().rstrip("/")
    secret = (settings.internal_paid_api_secret or "").strip()
    if not base or not secret:
        return ResellerResult("skipped")

    key = spend_key()
    reserved = _usd_to_micros(settings.reseller_max_price_usd)
    if not await reserve_budget(key, reserved):
        return ResellerResult("skipped")

    release = reserved  # what to give back; set to 0 when the outcome is ambiguous
    result = ResellerResult("failed", paid=None)
    status: int | None = None
    try:
        try:
            async with httpx.AsyncClient(timeout=CALL_TIMEOUT_SECONDS, follow_redirects=False) as client:
                resp = await client.post(
                    f"{base}{BUY_PATH}",
                    headers={"X-Beam-Internal-Secret": secret, "Content-Type": "application/json"},
                    json={"email": email},
                )
        except httpx.HTTPError as exc:
            # May or may not have paid — keep the whole reservation.
            logger.warning("reseller_apollo_call_failed", error=type(exc).__name__)
            release = 0
            return result

        status = resp.status_code
        try:
            body = resp.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            body = {}

        if status == 200 and body.get("provider") == PROVIDER:
            amount = _parse_amount(body.get("amount_usd"))
            meta = {"protocol": body.get("protocol"), "transaction": body.get("transaction")}
            if amount is None or _usd_to_micros(amount) > reserved:
                # Unknown/odd price: keep the full reservation, record the cap.
                release = 0
                amount = Decimal(str(settings.reseller_max_price_usd))
            else:
                release = reserved - _usd_to_micros(amount)
            result = _result_from_person(_person_from(body.get("data")), amount, True, meta)
        elif 200 <= status < 300:
            # Upstream answered without asking for payment (route passthrough).
            result = _result_from_person(_person_from(body), Decimal(0), False, {"unpaid": True})
        elif status == 402 and body.get("error") in _NOT_PAID_402:
            # Nothing was paid. A pending/declined approval may succeed later
            # ("failed" = retry another day); cap/no-offer answers will not.
            reason = body.get("error")
            outcome: Outcome = "failed" if reason == "payment_pending_or_declined" else "skipped"
            result = ResellerResult(outcome, paid=False, meta={"reason": reason})
        elif status == 502 and body.get("error") == "upstream_error":
            paid = body.get("paid")
            if paid is False:
                result = ResellerResult("failed", paid=False)
            else:
                release = 0
                result = ResellerResult(
                    "failed",
                    amount_usd=float(settings.reseller_max_price_usd) if paid is True else 0.0,
                    paid=True if paid is True else None,
                )
        else:
            # 404 (route dormant/secret mismatch), 4xx/5xx from our own route,
            # or an unpaid upstream error passed through: nothing was paid.
            result = ResellerResult("failed", paid=False)
        return result
    finally:
        if release > 0:
            await release_budget(key, release)
        logger.info("reseller_apollo_result", outcome=result.outcome, status=status, paid=result.paid)
        if status is not None or result.paid is None:
            await log_api_call(
                provider=PROVIDER,
                category="enrichment",
                operation="person_enrich",
                success=result.outcome in ("match", "no_match"),
                cost_usd=result.amount_usd,
                site_id=site_id,
                visitor_id=visitor_id,
                meta={k: v for k, v in {**result.meta, "paid": result.paid, "status": status}.items() if v is not None},
            )


async def enrich_via_reseller(
    email: str, *, site_id: str | None = None, visitor_id: str | None = None
) -> dict | None:
    """Mapped Apollo profile dict (same shape as ``_enrich_apollo``) or None."""
    result = await purchase_apollo_person(email, site_id=site_id, visitor_id=visitor_id)
    return result.data if result.outcome == "match" else None
