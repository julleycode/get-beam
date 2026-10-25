"""InFlow x402 seller — pay-per-call gate for /api/v1/paid/*.

Wiring (approach A1): the InFlow Python SDK (``inflowpay[x402]``) supplies the
``Seller`` (offers built from the account's InFlow config) and the
``Facilitator`` (verify/settle against InFlow, incl. the 409
``idempotency_pending`` settle retry and the 412 ``permit2_allowance_required``
verify mapping). The upstream ``x402`` package's ``x402HTTPResourceServer``
owns the wire protocol (PAYMENT-REQUIRED / PAYMENT-SIGNATURE or X-PAYMENT /
PAYMENT-RESPONSE headers and the 402 shape). We do NOT use the SDK's FastAPI
middleware (``inflowpay[fastapi]`` needs fastapi>=0.142; we pin 0.115.0) —
instead :func:`run_paid` drives the same verify -> handler -> settle sequence per
route, which also lets us add replay caching around it.

Per-request flow (:func:`run_paid`):

1. Replay check — if the presented payment payload already settled, return the
   cached response (+ original PAYMENT-RESPONSE). The handler is NOT re-run.
2. ``process_http_request`` — no/invalid payment => 402 with requirements.
3. Claim the payload in ``paid_requests`` (``pending``). A concurrent duplicate
   gets 409; a previously failed claim may be retried.
4. Run the handler. Exception => cancel, no settle, 5xx, claim => handler_failed.
5. Settle. Failure => 402 + PAYMENT-RESPONSE (success=false), logged as
   ``paid_settle_failed`` (we served content we were not paid for).
6. Success => 200 + PAYMENT-RESPONSE, claim => settled with tx/amount/payer.

Paid handlers MUST be read-only (no user-visible state): settlement happens
after the handler, so a handler that wrote state would leave it behind when
settlement fails.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from apps.api.config import settings

logger = structlog.get_logger()

INFLOW_NETWORK = "inflow:1"
INFLOW_SCHEMES = ["balance"]

# Header names (case-insensitive on the wire). Kept here so main.py's request-log
# redaction and the tests share one list.
PAYMENT_HEADERS = ("payment-signature", "x-payment", "payment-response", "x-payment-response")


def redact_payment_headers(headers: dict[str, str]) -> dict[str, str]:
    """Mask x402 payment headers (signed payment payloads / receipts) before logging.

    Pure — safe to import from main.py without pulling in the x402 SDK.
    """
    return {k: ("***" if k.lower() in PAYMENT_HEADERS else v) for k, v in headers.items()}


class PaymentHandlerError(Exception):
    """Raised by a paid handler to fail the request WITHOUT settling.

    ``status`` is returned to the buyer (e.g. 503 when the upstream provider is
    down). The buyer's signed payment is not settled, so it is not charged.
    """

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


# ─── Replay / reconciliation store ───────────────────────────────────────────


@dataclass
class CachedPaidResponse:
    status: int
    body: Any
    payment_response_header: str | None


class PaidRequestStore(Protocol):
    async def get_settled(self, payment_hash: str) -> CachedPaidResponse | None: ...

    async def claim(self, payment_hash: str, route_id: str) -> str:
        """Return ``"claimed"``, ``"settled"`` (replay) or ``"in_flight"``."""
        ...

    async def mark_failed(self, payment_hash: str, status: str, reason: str) -> None: ...

    async def mark_settled(
        self,
        payment_hash: str,
        *,
        response_status: int,
        response_body: Any,
        payment_response_header: str | None,
        scheme: str | None,
        network: str | None,
        asset: str | None,
        amount: str | None,
        payer: str | None,
        transaction: str | None,
    ) -> None: ...


class SqlPaidRequestStore:
    """``paid_requests`` table store (unique ``payment_hash``)."""

    async def get_settled(self, payment_hash: str) -> CachedPaidResponse | None:
        from sqlalchemy import select

        from apps.api.models.database import async_session
        from apps.api.models.paid_request import PaidRequest

        async with async_session() as db:
            row = (
                await db.execute(
                    select(PaidRequest).where(
                        PaidRequest.payment_hash == payment_hash,
                        PaidRequest.status == "settled",
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return CachedPaidResponse(
                status=row.response_status or 200,
                body=row.response_body,
                payment_response_header=row.payment_response_header,
            )

    async def claim(self, payment_hash: str, route_id: str) -> str:
        from sqlalchemy import select, update
        from sqlalchemy.dialects.postgresql import insert

        from apps.api.models.database import async_session
        from apps.api.models.paid_request import PaidRequest

        async with async_session() as db:
            inserted = (
                await db.execute(
                    insert(PaidRequest)
                    .values(payment_hash=payment_hash, route_id=route_id, status="pending")
                    .on_conflict_do_nothing(index_elements=["payment_hash"])
                    .returning(PaidRequest.id)
                )
            ).scalar_one_or_none()
            if inserted is not None:
                await db.commit()
                return "claimed"
            # Existing row: re-claim only a FAILED attempt (atomic compare-and-set).
            reclaimed = (
                await db.execute(
                    update(PaidRequest)
                    .where(
                        PaidRequest.payment_hash == payment_hash,
                        PaidRequest.status.in_(("handler_failed", "settle_failed")),
                    )
                    .values(status="pending", route_id=route_id, error_reason=None)
                    .returning(PaidRequest.id)
                )
            ).scalar_one_or_none()
            await db.commit()
            if reclaimed is not None:
                return "claimed"
            status = (
                await db.execute(
                    select(PaidRequest.status).where(PaidRequest.payment_hash == payment_hash)
                )
            ).scalar_one_or_none()
            return "settled" if status == "settled" else "in_flight"

    async def mark_failed(self, payment_hash: str, status: str, reason: str) -> None:
        from sqlalchemy import update

        from apps.api.models.database import async_session
        from apps.api.models.paid_request import PaidRequest

        async with async_session() as db:
            await db.execute(
                update(PaidRequest)
                .where(PaidRequest.payment_hash == payment_hash)
                .values(status=status, error_reason=reason[:256])
            )
            await db.commit()

    async def mark_settled(self, payment_hash: str, **fields: Any) -> None:
        from sqlalchemy import update

        from apps.api.models.database import async_session
        from apps.api.models.paid_request import PaidRequest

        async with async_session() as db:
            await db.execute(
                update(PaidRequest)
                .where(PaidRequest.payment_hash == payment_hash)
                .values(status="settled", error_reason=None, **fields)
            )
            await db.commit()


# ─── Gate (process-wide singleton, built at startup) ─────────────────────────


@dataclass
class PaymentGate:
    http_server: Any  # x402.http.x402HTTPResourceServer
    store: PaidRequestStore
    closers: list[Callable[[], Awaitable[None]]]


_gate: PaymentGate | None = None


def get_gate() -> PaymentGate | None:
    return _gate


def set_gate(gate: PaymentGate | None) -> None:
    global _gate
    _gate = gate


# route_id -> (HTTP method + path, settings attr holding the price)
PAID_ROUTES: dict[str, tuple[str, str]] = {
    "company-from-domain": (
        "POST /api/v1/paid/company-from-domain",
        "paid_price_company_from_domain",
    ),
    "social-posts": ("POST /api/v1/paid/social-posts", "paid_price_social_posts"),
    "generate-draft": ("POST /api/v1/paid/generate-draft", "paid_price_generate_draft"),
    "detect-platform": ("POST /api/v1/paid/detect-platform", "paid_price_detect_platform"),
}


def build_http_server(
    resource_server: Any, offers_by_route: dict[str, list[Any]]
) -> Any:
    """Build + initialize the x402 HTTP server for the paid routes.

    ``resource_server`` must already have its schemes registered.
    """
    from x402.http import x402HTTPResourceServer
    from x402.http.types import RouteConfig

    routes = {
        PAID_ROUTES[route_id][0]: RouteConfig(accepts=offers)
        for route_id, offers in offers_by_route.items()
    }
    http_server = x402HTTPResourceServer(resource_server, routes)
    http_server.initialize()  # validates schemes vs facilitator /supported
    return http_server


async def setup_gate() -> PaymentGate | None:
    """Create the InFlow Seller + Facilitator and the x402 HTTP server.

    Called from the API lifespan only when ``inflow_x402_enabled`` and an API key
    is set. Never raises: a failure is logged and the paid routes answer 503, so a
    misconfigured InFlow account can never take the whole API down.
    """
    if not (settings.inflow_x402_enabled and settings.inflow_api_key):
        if settings.inflow_x402_enabled:
            logger.warning("inflow_x402_disabled_no_api_key")
        return None
    try:
        from inflowpay import ClientOptions

        options = ClientOptions(
            environment=(
                "production" if settings.inflow_environment == "production" else "sandbox"
            ),
            api_key=settings.inflow_api_key,
            base_url=settings.inflow_base_url or None,
        )
        gate = await build_gate(options, SqlPaidRequestStore())
        set_gate(gate)
        logger.info("inflow_x402_ready", environment=options.environment, routes=sorted(PAID_ROUTES))
        return gate
    except Exception as exc:  # noqa: BLE001 — never block API boot on the seller
        # type + message only; the SDK never puts the API key in error text.
        logger.error("inflow_x402_setup_failed", error_type=type(exc).__name__, error=str(exc)[:300])
        return None


async def build_gate(options: Any, store: PaidRequestStore) -> PaymentGate:
    """Seller + Facilitator (InFlow SDK) -> x402 resource server -> PaymentGate.

    Split from :func:`setup_gate` so tests can inject a fake InFlow HTTP API via
    ``ClientOptions(transport=...)`` and exercise the real SDK end to end.
    Closes any client it opened if setup fails, then re-raises.
    """
    from x402 import x402ResourceServer

    from inflowpay.x402.facilitator import Facilitator
    from inflowpay.x402.seller import Seller

    seller = facilitator = None
    try:
        seller = await Seller.create(options)
        facilitator = await Facilitator.create(options)
        resource_server = x402ResourceServer(facilitator)
        for registration in await seller.scheme_registrations(schemes=INFLOW_SCHEMES):
            resource_server.register(registration["network"], registration["server"])

        offers_by_route: dict[str, list[Any]] = {}
        for route_id, (_, price_attr) in PAID_ROUTES.items():
            offers = await seller.offers(
                getattr(settings, price_attr), schemes=INFLOW_SCHEMES, networks=[INFLOW_NETWORK]
            )
            if not offers:
                raise ValueError(f"InFlow account has no balance/{INFLOW_NETWORK} offer")
            offers_by_route[route_id] = offers

        return PaymentGate(
            http_server=build_http_server(resource_server, offers_by_route),
            store=store,
            closers=[facilitator.aclose, seller.aclose],
        )
    except BaseException:
        for client in (facilitator, seller):
            if client is not None:
                try:
                    await client.aclose()
                except Exception:  # noqa: BLE001
                    pass
        raise


async def teardown_gate() -> None:
    gate = get_gate()
    set_gate(None)
    if gate is None:
        return
    for close in gate.closers:
        try:
            await close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("inflow_x402_close_failed", error_type=type(exc).__name__)


# ─── Per-request flow ────────────────────────────────────────────────────────


def _payment_header(request: Request) -> str | None:
    # x402 v2 only (InFlow is v2-only): the upstream server reads PAYMENT-SIGNATURE
    # and ignores the v1 X-PAYMENT header, so the replay key must use the same one.
    return request.headers.get("payment-signature")


def payment_hash(header_value: str) -> str | None:
    """sha256 of the canonical decoded payment payload (None if undecodable).

    Hashing the canonical JSON (not the raw base64) makes whitespace/key-order
    re-encodings of the same signed payload collide, as they should.
    """
    from x402.http.utils import safe_base64_decode

    try:
        data = json.loads(safe_base64_decode(header_value))
    except Exception:  # noqa: BLE001 — x402 will answer 402 for a malformed header
        return None
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _instructions_to_response(instr: Any, *, fallback_body: Any = None) -> Response:
    if instr.is_html:
        return Response(
            content=instr.body, status_code=instr.status, headers=instr.headers,
            media_type="text/html",
        )
    body = instr.body if instr.body else (fallback_body if fallback_body is not None else {})
    headers = {k: v for k, v in instr.headers.items() if k.lower() != "content-type"}
    return JSONResponse(content=body, status_code=instr.status, headers=headers)


def _decoded_payment_required(headers: dict[str, str]) -> Any:
    """The PAYMENT-REQUIRED header decoded, mirrored into the 402 JSON body.

    v2 clients read the header; mirroring it into the body helps humans and
    agents that only look at the body. Same content, no extra disclosure.
    """
    from x402.http.utils import safe_base64_decode

    for key, value in headers.items():
        if key.lower() == "payment-required":
            try:
                return json.loads(safe_base64_decode(value))
            except Exception:  # noqa: BLE001
                return None
    return None


async def run_paid(
    request: Request,
    route_id: str,
    handler: Callable[[], Awaitable[dict]],
) -> Response:
    """Gate ``handler`` behind an x402 payment. See module docstring."""
    from x402.http.middleware.fastapi import FastAPIAdapter
    from x402.http.types import HTTPRequestContext, HTTPTransportContext
    from x402.schemas import VerifiedPaymentCancelOptions

    gate = get_gate()
    if gate is None:
        return JSONResponse({"detail": "Paid API temporarily unavailable"}, status_code=503)

    header = _payment_header(request)
    phash = payment_hash(header) if header else None

    # 1. Replay of an already-settled payment -> cached response, no upstream call.
    if phash:
        cached = await gate.store.get_settled(phash)
        if cached is not None:
            logger.info("paid_replay_served", route=route_id)
            headers = {"Cache-Control": "private, no-store"}
            if cached.payment_response_header:
                headers["PAYMENT-RESPONSE"] = cached.payment_response_header
            return JSONResponse(content=cached.body, status_code=cached.status, headers=headers)

    adapter = FastAPIAdapter(request)
    context = HTTPRequestContext(
        adapter=adapter,
        path=request.url.path,
        method=request.method,
        payment_header=header,
    )

    # 2. Verify (or answer 402 with requirements).
    try:
        result = await gate.http_server.process_http_request(context)
    except Exception as exc:  # noqa: BLE001
        logger.error("paid_verify_error", route=route_id, error_type=type(exc).__name__)
        return JSONResponse({"detail": "Payment facilitator error"}, status_code=502)

    if result.type == "payment-error":
        if result.response is None:
            return JSONResponse({"detail": "Payment required"}, status_code=402)
        return _instructions_to_response(
            result.response, fallback_body=_decoded_payment_required(result.response.headers)
        )
    if result.type != "payment-verified" or phash is None:
        # Route not configured for payment — fail CLOSED, never serve for free.
        logger.error("paid_route_unprotected", route=route_id, result=result.type)
        return JSONResponse({"detail": "Paid API misconfigured"}, status_code=503)

    requirements = result.payment_requirements
    dispatcher = result.cancellation_dispatcher

    # 3. Claim the payload (concurrency-safe replay guard).
    claim = await gate.store.claim(phash, route_id)
    if claim == "settled":
        cached = await gate.store.get_settled(phash)
        if cached is not None:
            headers = {"Cache-Control": "private, no-store"}
            if cached.payment_response_header:
                headers["PAYMENT-RESPONSE"] = cached.payment_response_header
            return JSONResponse(content=cached.body, status_code=cached.status, headers=headers)
    if claim != "claimed":
        return JSONResponse(
            {"detail": "This payment is already being processed"}, status_code=409
        )

    # 4. Run the (read-only) handler.
    try:
        body = await handler()
    except Exception as exc:  # noqa: BLE001
        status = exc.status if isinstance(exc, PaymentHandlerError) else 500
        detail = exc.detail if isinstance(exc, PaymentHandlerError) else "Internal Server Error"
        if dispatcher is not None:
            try:
                await dispatcher.cancel(
                    VerifiedPaymentCancelOptions(reason="handler_threw", error=exc)
                )
            except Exception:  # noqa: BLE001
                logger.warning("paid_cancel_failed", route=route_id)
        await gate.store.mark_failed(phash, "handler_failed", type(exc).__name__)
        logger.warning(
            "paid_handler_failed_not_settled", route=route_id, error_type=type(exc).__name__
        )
        return JSONResponse({"detail": detail}, status_code=status)

    # 5. Settle.
    try:
        settle = await gate.http_server.process_settlement(
            result.payment_payload,
            requirements,
            context=context,
            declared_extensions=result.declared_extensions,
            transport_context=HTTPTransportContext(request=context),
            before_handler_settlement=result.before_handler_settlement,
        )
    except Exception as exc:  # noqa: BLE001
        settle = None
        settle_error = type(exc).__name__
    else:
        settle_error = settle.error_reason if not settle.success else None

    if settle is None or not settle.success:
        await gate.store.mark_failed(phash, "settle_failed", settle_error or "unknown")
        # Revenue loss signal: content was produced, payment did not land.
        logger.error(
            "paid_settle_failed",
            route=route_id,
            reason=settle_error,
            amount=getattr(requirements, "amount", None),
            network=getattr(requirements, "network", None),
        )
        if settle is not None and settle.response is not None:
            return _instructions_to_response(settle.response)
        return JSONResponse(
            {"detail": "Payment settlement failed"},
            status_code=402,
            headers={"Cache-Control": "private, no-store"},
        )

    # 6. Success.
    payment_response = settle.headers.get("PAYMENT-RESPONSE")
    await gate.store.mark_settled(
        phash,
        response_status=200,
        response_body=body,
        payment_response_header=payment_response,
        scheme=getattr(requirements, "scheme", None),
        network=settle.network or getattr(requirements, "network", None),
        asset=getattr(requirements, "asset", None),
        amount=getattr(requirements, "amount", None),
        payer=settle.payer,
        transaction=settle.transaction,
    )
    logger.info(
        "paid_request_settled",
        route=route_id,
        amount=getattr(requirements, "amount", None),
        network=settle.network,
        transaction=settle.transaction,
    )
    headers = {**settle.headers, "Cache-Control": "private, no-store"}
    return JSONResponse(content=body, status_code=200, headers=headers)
