"""Public read-only MCP server, hand-written JSON-RPC 2.0 (agent-gateway Phase 2).

    POST /api/v1/agent/{site_id}/mcp

Deliberately NOT built on an MCP SDK: no `mcp` package exists in
requirements.txt, and three read-only tools do not justify adding one (plan
instruction E3). This is a minimal, strict JSON-RPC 2.0 dispatcher.

Four guards, all required by E3, none optional:

1. **Rate limit** — the same ``@limiter.limit`` budget as the sibling REST
   routes. This is the only body-accepting route in Phase 1+2 scope; leaving it
   unrated would make it the cheapest way to hammer the gateway.
2. **Body-size cap** — enforced from Content-Length AND from the actual read
   bytes, BEFORE any JSON parsing, so a forged/absent header cannot get a
   multi-megabyte blob into the parser.
3. **Strict method allow-list** — only ``tools/list``, ``tools/call`` and the
   three named read tools in ``MCP_TOOLS``. Anything else is -32601.
4. **No raw-input echo** — error responses carry fixed, static strings only.
   Reflecting attacker-controlled bytes back would turn this into a reflection
   gadget. The one echoed value is the JSON-RPC ``id``, and only when it is a
   scalar of a permitted type (see ``_safe_id``).

Same double gating and same tenant-exposure posture as the REST routes: flag
off / unknown site / no profile / disabled profile all produce one identical
HTTP 404, never a 403 and never a distinguishing error.

Phase 3 wires the action tools. They are not present here.
"""

import json

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.database import get_db
from apps.api.schemas.agent_gateway import REQUIRED_QUALIFICATION_PARAMS
from apps.api.services.agent_gateway import (
    CONVERSION_TOOLS,
    MCP_TOOLS,
    handle_conversion_tool,
    has_malformed_qualification_params,
    missing_qualification_params,
    resolve_public_profile,
    sanitize_qualification_params,
)
from apps.api.services.ip_resolution import resolve_client_ip
from apps.api.services.rate_limiter import limiter

router = APIRouter()
logger = structlog.get_logger()

MCP_RATE_LIMIT = "60/minute"

# WS3 MCP lifecycle handshake — STATIC values only. Never the real internal
# service version, build hash, or any per-site dynamic data (no info leak).
MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_SERVER_NAME = "beam-agent-concierge"
MCP_SERVER_VERSION = "1.0.0"

# Custom (out-of-band) JSON-RPC application error for a tripped conversion-tool
# rate limit. Outside the reserved -32768..-32000 standard range on purpose.
_RATE_LIMITED = -32010

# 16 KB. A legitimate JSON-RPC read call is a few hundred bytes; this leaves
# three orders of magnitude of headroom while keeping the parser off anything
# large. Independent of the global ingest body cap, which is scoped to /ingest.
MAX_MCP_BODY_BYTES = 16 * 1024

# JSON-RPC 2.0 standard error codes.
_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602

_NOT_FOUND = HTTPException(status_code=404, detail="Not found")


def _safe_id(raw):
    """Echo the request id back only when it is a plain scalar of a sane size.

    JSON-RPC says the id must be echoed, but the id is attacker-controlled. A
    huge string or a nested object would let a caller choose our response body.
    Anything unexpected degrades to null rather than being reflected.
    """
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return raw
    if isinstance(raw, str) and len(raw) <= 128:
        return raw
    return None


def _error(request_id, code: int, message: str) -> dict:
    """Build a JSON-RPC error object. ``message`` MUST be a fixed literal from
    this module — never interpolated from request data."""
    return {
        "jsonrpc": "2.0",
        "id": _safe_id(request_id),
        "error": {"code": code, "message": message},
    }


def _result(request_id, payload: dict) -> dict:
    return {"jsonrpc": "2.0", "id": _safe_id(request_id), "result": payload}


def _qualification_input_schema() -> dict:
    """inputSchema advertising the 3 required qualification params. Advisory
    only — the server-side gate is the real enforcement; this lets a
    spec-conformant client pre-validate."""
    return {
        "type": "object",
        "properties": {
            "use_case": {"type": "string"},
            "company_size": {"type": "string"},
            "evaluating_against": {"type": "string"},
        },
        "required": list(REQUIRED_QUALIFICATION_PARAMS),
    }


def _tools_list() -> dict:
    """Advertise the available tools. Flag-aware:

    - qualification OFF (default): the 3 read tools with an empty inputSchema —
      byte-identical to the pre-WS3 surface.
    - qualification ON: the same 3 tools gain the required-params inputSchema.
    - conversion ON: the 2 conversion tools are appended; OFF (default): absent.
    """
    gated = settings.agent_concierge_qualification_enabled
    read_schema = _qualification_input_schema() if gated else {
        "type": "object", "properties": {}
    }
    tools = [
        {
            "name": "get_offers",
            "description": "List everything this business sells.",
            "inputSchema": read_schema,
        },
        {
            "name": "get_pricing",
            "description": "Prices for everything this business sells.",
            "inputSchema": read_schema,
        },
        {
            "name": "check_availability",
            "description": "Availability for everything this business sells.",
            "inputSchema": read_schema,
        },
    ]
    if settings.agent_concierge_conversion_enabled:
        tools += [
            {
                "name": "request_quote",
                "description": "Request a tailored quote. Creates a real lead.",
                "inputSchema": _qualification_input_schema(),
            },
            {
                "name": "book_demo",
                "description": "Request a demo. Creates a real lead.",
                "inputSchema": _qualification_input_schema(),
            },
        ]
    return {"tools": tools}


def _initialize_result() -> dict:
    """Static MCP lifecycle handshake — no dynamic/internal data."""
    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": MCP_SERVER_NAME, "version": MCP_SERVER_VERSION},
    }


def _extract_arguments(params) -> dict:
    """Pull the tool arguments out of a tools/call params object. MCP nests them
    under ``arguments``; tolerate a flat dict for simple clients."""
    if not isinstance(params, dict):
        return {}
    args = params.get("arguments")
    if isinstance(args, dict):
        return args
    return {}


def _conversion_rate_limited(site_id: str) -> bool:
    """Must-Fix 1: a dedicated, tighter per-site rate limit for the conversion
    tools, via a manual limiter.hit() (NOT a route decorator — a decorator would
    rate-limit the WHOLE endpoint, not just this dispatch branch). Distinct
    namespace so it never collides with the shared read budget or the ingest
    ceiling. Fail-open: a storage error never blocks a legitimate lead."""
    try:
        from limits import RateLimitItemPerMinute

        item = RateLimitItemPerMinute(
            settings.agent_concierge_conversion_rate_limit_per_minute
        )
        # .hit() returns False once the window's allowance is exhausted.
        return not limiter.limiter.hit(item, "mcp_conversion_tool", site_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("mcp_conversion_rate_check_failed", error=str(exc))
        return False


async def _record_tool_call(
    db: AsyncSession,
    site_id: str,
    method: str,
    tool_name: str | None,
    args: dict,
    is_gated: bool,
) -> None:
    """WS3 kill-test instrumentation. Append one agent_tool_calls row. FAIL-OPEN
    — instrumentation must never break a response. Only recorded while the
    concierge experiment is active on this deployment (either flag on); when both
    flags are off, behavior is byte-identical to today (no new writes)."""
    if not (
        settings.agent_concierge_qualification_enabled
        or settings.agent_concierge_conversion_enabled
    ):
        return
    try:
        from apps.api.models.agent_tool_call import AgentToolCall

        provided = {
            name: bool(isinstance(args.get(name), str) and args.get(name).strip())
            for name in REQUIRED_QUALIFICATION_PARAMS
        }
        complete = all(provided.values())
        db.add(
            AgentToolCall(
                site_id=site_id,
                method=method,
                tool_name=tool_name,
                params_provided=provided,
                params_complete=complete,
                is_gated_tool=is_gated,
            )
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        try:
            await db.rollback()
        except Exception:
            pass
        logger.warning("mcp_tool_call_metric_failed", error=str(exc))


@router.post("/{site_id}/mcp")
@limiter.limit(MCP_RATE_LIMIT)
async def mcp_endpoint(
    request: Request,
    site_id: str,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    # ── Gate 1: tenancy + flags, before anything else is done with the body.
    resolved = await resolve_public_profile(db, site_id)
    if resolved is None:
        raise _NOT_FOUND
    site, profile = resolved

    # ── Gate 2: body size, checked twice (declared then actual) before parsing.
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > MAX_MCP_BODY_BYTES:
                raise HTTPException(status_code=413, detail="Request body too large")
        except ValueError:
            # Unparseable Content-Length — fall through to the actual-bytes
            # check rather than trusting the header either way.
            pass

    raw = await request.body()
    if len(raw) > MAX_MCP_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Request body too large")

    # ── Gate 3: parse. Failures return a fixed message, never the input.
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return JSONResponse(_error(None, _PARSE_ERROR, "Parse error"))

    if not isinstance(payload, dict):
        # Batch requests (a JSON array) are deliberately unsupported: they
        # multiply work per rate-limit token.
        return JSONResponse(_error(None, _INVALID_REQUEST, "Invalid Request"))

    request_id = payload.get("id")

    if payload.get("jsonrpc") != "2.0":
        return JSONResponse(_error(request_id, _INVALID_REQUEST, "Invalid Request"))

    method = payload.get("method")
    if not isinstance(method, str):
        return JSONResponse(_error(request_id, _INVALID_REQUEST, "Invalid Request"))

    # ── Gate 4: strict method allow-list.
    if method == "initialize":
        return JSONResponse(_result(request_id, _initialize_result()))

    if method == "tools/list":
        await _record_tool_call(db, site_id, "tools/list", None, {}, False)
        return JSONResponse(_result(request_id, _tools_list()))

    if method == "tools/call":
        params = payload.get("params")
        if not isinstance(params, dict):
            return JSONResponse(_error(request_id, _INVALID_PARAMS, "Invalid params"))
        tool_name = params.get("name")
        if not isinstance(tool_name, str):
            return JSONResponse(
                _error(request_id, _METHOD_NOT_FOUND, "Method not found")
            )
        args = _extract_arguments(params)
        return await _dispatch_tool(db, request, site, profile, request_id, tool_name, args)

    # Direct tool invocation as a bare method, for simple clients. Any flat dict
    # under ``params`` is treated as the tool arguments.
    if method in MCP_TOOLS or method in CONVERSION_TOOLS:
        raw_params = payload.get("params")
        args = raw_params if isinstance(raw_params, dict) else {}
        return await _dispatch_tool(db, request, site, profile, request_id, method, args)

    return JSONResponse(_error(request_id, _METHOD_NOT_FOUND, "Method not found"))


async def _dispatch_tool(
    db: AsyncSession,
    request: Request,
    site,
    profile,
    request_id,
    tool_name: str,
    args: dict,
) -> JSONResponse:
    """Shared tool dispatch for both the tools/call wrapper and the bare-method
    path. Applies the WS3 qualification gate, the conversion-tool branch (rate
    limit + Must-Fix 3 free lookup + fail-open notification), and kill-test
    instrumentation. The 3 read tools stay ungated + byte-identical when the
    qualification flag is off."""
    # ── Conversion tools (write path) — gated behind the conversion flag ──
    if tool_name in CONVERSION_TOOLS:
        if not settings.agent_concierge_conversion_enabled:
            # OFF => behave as if the tool does not exist (same posture as an
            # unrecognized method).
            return JSONResponse(
                _error(request_id, _METHOD_NOT_FOUND, "Method not found")
            )
        # Malformed (present-but-wrong-typed) params => -32602, distinct from
        # absent params (handled as needs_more_info inside handle_conversion_tool).
        if has_malformed_qualification_params(args):
            return JSONResponse(_error(request_id, _INVALID_PARAMS, "Invalid params"))
        # Must-Fix 1: dedicated tighter rate limit, per site.
        if _conversion_rate_limited(site.site_id):
            return JSONResponse(
                _error(request_id, _RATE_LIMITED, "Rate limit exceeded"),
                status_code=429,
            )
        # Must-Fix 2: sanitize at the entry point before anything downstream.
        clean_args = sanitize_qualification_params(args)
        ip_address = resolve_client_ip(request)
        result = await handle_conversion_tool(
            db, site, profile, tool_name, clean_args, ip_address
        )
        await _record_tool_call(
            db, site.site_id, "tools/call", tool_name, clean_args, True
        )
        return JSONResponse(_result(request_id, result))

    # ── Read tools ──
    if tool_name not in MCP_TOOLS:
        return JSONResponse(_error(request_id, _METHOD_NOT_FOUND, "Method not found"))

    gated = settings.agent_concierge_qualification_enabled
    clean_args = sanitize_qualification_params(args) if gated else {}
    if gated:
        if has_malformed_qualification_params(args):
            return JSONResponse(_error(request_id, _INVALID_PARAMS, "Invalid params"))
        missing = missing_qualification_params(args)
        await _record_tool_call(
            db, site.site_id, "tools/call", tool_name, clean_args, True
        )
        if missing:
            from apps.api.schemas.agent_gateway import NeedsMoreInfoOut

            return JSONResponse(
                _result(
                    request_id,
                    NeedsMoreInfoOut(missing_params=missing).model_dump(),
                )
            )
        return JSONResponse(
            _result(request_id, MCP_TOOLS[tool_name](site, profile, clean_args))
        )

    # Ungated legacy path — byte-identical to pre-WS3.
    await _record_tool_call(db, site.site_id, "tools/call", tool_name, {}, False)
    return JSONResponse(_result(request_id, MCP_TOOLS[tool_name](site, profile)))
