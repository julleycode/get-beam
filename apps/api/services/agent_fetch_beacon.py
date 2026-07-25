"""Server-side AI-fetch beacon business logic (Handoff Detection H5).

Classifies an on-demand AI-fetcher User-Agent forwarded by the getbeam.fyi edge
middleware and writes BOTH an ``agent_visit`` rollup row and an append-only
``agent_fetch_event`` row — the same two tables the pixel ingest path writes,
so the existing Agents dashboard + the 10-min handoff-correlation sweep light up
with zero frontend change.

GUARDRAIL (AC-H5-8, the program's highest priority): this module imports ZERO
identity/Visitor/IdentifiedVisitor path. It writes only to the two structurally
agent-only tables via the existing fail-open persistence functions. It NEVER
creates or touches a Visitor, an IdentifiedVisitor, or ``is_emailable_identity``.
A leaked/forged beacon can at worst add non-identity agent-dashboard rows.

PII/GDPR: logs keys/vendor/site_id only — NEVER the raw UA or an IP.
"""

from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.site import Site
from apps.api.schemas.agents import FetchBeaconIn
from apps.api.services.agent_classifier import classify_agent, classify_tier
from apps.api.services.agent_visit_persistence import (
    persist_agent_fetch_event,
    persist_agent_visit,
)

logger = structlog.get_logger()

# "p" + base36(unix-seconds), minted by apps/web/src/app/pricing-overview/route.ts.
# Decoding it (strip "p", base36→int seconds) recovers the exact page mint time.
_TOKEN_RE_PREFIX = "p"


def decode_token_mint_ts(token: str | None) -> datetime | None:
    """Decode a ``/pricing-overview/{token}`` token to its mint datetime (UTC).

    Token scheme (mirror of the web minter): ``"p" + base36(floor(Date.now()/1000))``.
    Returns ``None`` for an absent/malformed token — the caller then falls back
    to the server-receive time (``created_at`` server default). Never raises.
    """
    if not token or len(token) < 2 or token[0] != _TOKEN_RE_PREFIX:
        return None
    body = token[1:]
    # base36 alphabet only: 0-9a-z. Anything else is malformed → fall back.
    if not all(c.isdigit() or ("a" <= c <= "z") for c in body):
        return None
    try:
        secs = int(body, 36)
    except ValueError:
        return None
    if secs <= 0:
        return None
    try:
        return datetime.fromtimestamp(secs, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


async def record_fetch_beacon(db: AsyncSession, payload: FetchBeaconIn) -> str:
    """Classify + persist an AI-fetch beacon. Returns ``"written"`` or ``"noop"``.

    ``"noop"`` (endpoint maps to 204) for: unknown/unrecognized UA, an
    index-tier crawler (on-demand-only gating), or an unknown/foreign site_id
    (multi-tenant no-leak — never 403). ``"written"`` (202/204) only when an
    on-demand fetcher hits a known site. Fail-open: the underlying persistence
    functions swallow their own errors, so this never raises into the endpoint.
    """
    classification = classify_agent(payload.user_agent)
    if classification is None:
        # Junk / unknown / non-allowlisted UA — nothing to capture.
        return "noop"

    tier = classify_tier(classification.product_or_ua_token)
    if tier != "on-demand":
        # Index-tier crawler (e.g. gptbot, google-cloudvertexbot). Not a live
        # human-behind-the-agent fetch — do not fabricate a handoff signal.
        logger.info(
            "fetch_beacon_index_noop",
            site_id=payload.site_id,
            vendor=classification.vendor,
            tier=tier,
        )
        return "noop"

    # Multi-tenancy: resolve the site publicly (no Clerk). Unknown/foreign →
    # no-op, NEVER 403 (never leak id existence). Mirrors events.py Site lookup.
    site_row = await db.execute(
        select(Site.site_id).where(Site.site_id == payload.site_id).limit(1)
    )
    if site_row.scalar_one_or_none() is None:
        return "noop"

    mint_ts = decode_token_mint_ts(payload.token)

    # No fetcher IP is available server-side (the middleware forwards none, and
    # logging/storing an IP is a PII guardrail) — pass empty/None.
    await persist_agent_visit(db, payload.site_id, classification, "", payload.path)
    await persist_agent_fetch_event(
        db,
        payload.site_id,
        classification,
        tier,
        None,
        payload.path,
        event_time=mint_ts,
    )
    logger.info(
        "fetch_beacon_written",
        site_id=payload.site_id,
        vendor=classification.vendor,
        tier=tier,
        minted=mint_ts is not None,
    )
    return "written"
