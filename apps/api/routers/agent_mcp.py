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

from apps.api.models.database import get_db
from apps.api.services.agent_gateway import (
    MCP_TOOLS,
    SURFACE_MCP_TOOLS_LIST,
    mcp_tool_surface,
    record_gateway_visit,
    resolve_public_profile,
)
from apps.api.services.rate_limiter import limiter

router = APIRouter()
logger = structlog.get_logger()

MCP_RATE_LIMIT = "60/minute"

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


def _tools_list() -> dict:
    return {
        "tools": [
            {
                "name": "get_offers",
                "description": "List everything this business sells.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "get_pricing",
                "description": "Prices for everything this business sells.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "check_availability",
                "description": "Availability for everything this business sells.",
                "inputSchema": {"type": "object", "properties": {}},
            },
        ]
    }


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

    # ── Gate 4: strict method allow-list. Recording happens only past this gate,
    # so a malformed or rejected call never lands in the agent tables; the label
    # is always a fixed literal or a validated MCP_TOOLS key, never raw input.
    if method == "tools/list":
        await record_gateway_visit(db, request, site_id, SURFACE_MCP_TOOLS_LIST)
        return JSONResponse(_result(request_id, _tools_list()))

    if method == "tools/call":
        params = payload.get("params")
        if not isinstance(params, dict):
            return JSONResponse(_error(request_id, _INVALID_PARAMS, "Invalid params"))
        tool_name = params.get("name")
        if not isinstance(tool_name, str) or tool_name not in MCP_TOOLS:
            return JSONResponse(
                _error(request_id, _METHOD_NOT_FOUND, "Method not found")
            )
        await record_gateway_visit(db, request, site_id, mcp_tool_surface(tool_name))
        return JSONResponse(
            _result(request_id, MCP_TOOLS[tool_name](site, profile))
        )

    # Direct tool invocation as a bare method, for simple clients.
    if method in MCP_TOOLS:
        await record_gateway_visit(db, request, site_id, mcp_tool_surface(method))
        return JSONResponse(_result(request_id, MCP_TOOLS[method](site, profile)))

    return JSONResponse(_error(request_id, _METHOD_NOT_FOUND, "Method not found"))
