"""Agent-paid internal API — POST /internal/v1/paid/*.

Called ONLY by the apps/web route handler after it verifies an MPP/x402
payment; external agents never reach these routes directly. Mounted outside
/api/v1 and hidden from the OpenAPI schema.

Gate order per request (load-bearing — see tests/unit/test_agent_paid_internal.py):

1. ``require_internal_secret`` (router-level dependency): flag off, empty
   configured secret, or a missing/mismatched ``X-Beam-Internal-Secret`` →
   plain 404, indistinguishable from an unknown route. FastAPI resolves
   dependencies BEFORE invoking the endpoint callable, and slowapi's
   ``@limiter.limit`` check lives inside that callable's wrapper — so an
   unauthenticated caller can neither consume nor probe a rate-limit bucket.
   The endpoints declare NO body parameter, so FastAPI does not read or parse
   the body before this dependency either.
2. slowapi limit (``settings.agent_paid_rate_limit``) keyed on
   ``X-Beam-Client-IP`` — trusted only because step 1 passed.
3. Body cap (``settings.agent_paid_max_body_bytes``): Content-Length AND the
   actual streamed bytes → 413. Then Pydantic validation → 422.
4. Work (``services/agent_paid.py``).

No-match is ``404 {"error": "no_match"}`` — the web handler relies on this exact
shape to skip settlement. Upstream failure is 502, privacy-gate failure 503.
"""

import hmac
import ipaddress
import time
from typing import TypeVar

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from apps.api.config import settings
from apps.api.schemas.agent_paid import (
    DeepResearchRequest,
    DeepResearchResponse,
    EnrichEmailRequest,
    EnrichEmailResponse,
    IpCompanyRequest,
    IpCompanyResponse,
    OutreachDraftRequest,
    OutreachDraftResponse,
)
from apps.api.services import agent_paid as svc
from apps.api.services.ip_resolution import resolve_client_ip
from apps.api.services.rate_limiter import limiter

logger = structlog.get_logger()

CLIENT_IP_HEADER = "x-beam-client-ip"
NO_MATCH_BODY = {"error": "no_match"}

ModelT = TypeVar("ModelT", bound=BaseModel)


def require_internal_secret(
    x_beam_internal_secret: str | None = Header(default=None),
) -> None:
    """Dormant-not-revealed shared-secret gate. Every failure is a plain 404.

    The empty-configured-secret check runs BEFORE ``hmac.compare_digest`` —
    ``compare_digest('', '')`` is True, so comparing an empty header against an
    empty secret would otherwise be an auth bypass.
    """
    configured = settings.internal_paid_api_secret
    if not settings.agent_paid_enabled or not configured:
        raise HTTPException(status_code=404, detail="Not Found")
    if not x_beam_internal_secret:
        raise HTTPException(status_code=404, detail="Not Found")
    if not hmac.compare_digest(
        x_beam_internal_secret.encode("utf-8"), configured.encode("utf-8")
    ):
        raise HTTPException(status_code=404, detail="Not Found")


def paid_client_ip_key(request: Request) -> str:
    """slowapi key_func: the agent's IP as forwarded by the web handler.

    Safe to trust only because ``require_internal_secret`` has already run. A
    malformed header is ignored (never used as a free-form bucket key); the
    fallback is the transport peer via the shared resolver.
    """
    raw = (request.headers.get(CLIENT_IP_HEADER) or "").strip()
    if raw:
        try:
            return f"paid:{ipaddress.ip_address(raw)}"
        except ValueError:
            pass
    return f"paid:{resolve_client_ip(request) or 'unknown'}"


def _paid_rate_limit() -> str:
    # Callable so the limit is read from settings per request, not frozen at import.
    return settings.agent_paid_rate_limit


router = APIRouter(
    prefix="/internal/v1/paid",
    tags=["agent-paid-internal"],
    dependencies=[Depends(require_internal_secret)],
    include_in_schema=False,
)


async def _read_body(request: Request, model: type[ModelT]) -> ModelT:
    """Read the body under the byte cap, then validate. 413 / 422 on failure."""
    cap = settings.agent_paid_max_body_bytes
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > cap:
                raise HTTPException(status_code=413, detail="payload_too_large")
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid_content_length")

    buf = bytearray()
    async for chunk in request.stream():
        buf.extend(chunk)
        if len(buf) > cap:
            raise HTTPException(status_code=413, detail="payload_too_large")

    try:
        return model.model_validate_json(bytes(buf))
    except ValidationError as exc:
        # loc/msg/type only — never echo the caller's input values back.
        detail = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        raise HTTPException(status_code=422, detail=detail)


def _log(route: str, outcome: str, started: float, provider: str | None = None) -> None:
    logger.info(
        "agent_paid_request",
        route=route,
        outcome=outcome,
        provider=provider,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


def _error(route: str, exc: Exception, started: float) -> JSONResponse:
    """Map service exceptions to the wire contract."""
    if isinstance(exc, svc.NoMatch):
        _log(route, "no_match", started)
        return JSONResponse(status_code=404, content=NO_MATCH_BODY)
    if isinstance(exc, svc.PrivacyGateUnavailable):
        _log(route, "privacy_gate_unavailable", started)
        return JSONResponse(status_code=503, content={"error": "unavailable"})
    _log(route, "upstream_error", started)
    return JSONResponse(status_code=502, content={"error": "upstream_error"})


_SERVICE_ERRORS = (svc.NoMatch, svc.UpstreamError, svc.PrivacyGateUnavailable)


@router.post("/enrich-email", response_model=EnrichEmailResponse)
@limiter.limit(_paid_rate_limit, key_func=paid_client_ip_key)
async def paid_enrich_email(request: Request):
    started = time.perf_counter()
    body = await _read_body(request, EnrichEmailRequest)
    try:
        data, provider = await svc.enrich_email(str(body.email))
    except _SERVICE_ERRORS as exc:
        return _error("enrich_email", exc, started)
    _log("enrich_email", "ok", started, provider)
    return EnrichEmailResponse.model_validate(data)


@router.post("/ip-company", response_model=IpCompanyResponse)
@limiter.limit(_paid_rate_limit, key_func=paid_client_ip_key)
async def paid_ip_company(request: Request):
    started = time.perf_counter()
    body = await _read_body(request, IpCompanyRequest)
    try:
        data = await svc.ip_company(body.ip)
    except svc.InvalidIp as exc:
        _log("ip_company", "invalid_ip", started)
        raise HTTPException(status_code=422, detail=str(exc))
    except _SERVICE_ERRORS as exc:
        return _error("ip_company", exc, started)
    _log("ip_company", "ok", started, data.get("source"))
    return IpCompanyResponse.model_validate(data)


@router.post("/deep-research", response_model=DeepResearchResponse)
@limiter.limit(_paid_rate_limit, key_func=paid_client_ip_key)
async def paid_deep_research(request: Request):
    started = time.perf_counter()
    body = await _read_body(request, DeepResearchRequest)
    try:
        data = await svc.deep_research(
            full_name=body.full_name,
            company_name=body.company_name,
            job_title=body.job_title,
            linkedin_url=body.linkedin_url,
            email=str(body.email) if body.email else None,
        )
    except _SERVICE_ERRORS as exc:
        return _error("deep_research", exc, started)
    _log("deep_research", "ok", started, "gemini")
    return DeepResearchResponse.model_validate(data)


@router.post("/outreach-draft", response_model=OutreachDraftResponse)
@limiter.limit(_paid_rate_limit, key_func=paid_client_ip_key)
async def paid_outreach_draft(request: Request):
    started = time.perf_counter()
    body = await _read_body(request, OutreachDraftRequest)
    try:
        data = await svc.outreach_draft(
            visitor_name=body.visitor_name,
            visitor_role=body.visitor_role,
            visitor_company=body.visitor_company,
            user_url=body.user_url,
            recent_post=body.recent_post,
        )
    except _SERVICE_ERRORS as exc:
        return _error("outreach_draft", exc, started)
    _log("outreach_draft", "ok", started, data.get("source"))
    return OutreachDraftResponse.model_validate(data)
