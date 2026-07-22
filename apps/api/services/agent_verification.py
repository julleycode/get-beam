"""IP-range verification for recognized AI-agent visits (EvalLayer Phase 4).

Upgrades an agent-visit's confidence from ``ua-only`` to ``ip-verified`` by
cross-checking a small, checked-in static set of published vendor CIDR ranges
(OpenAI, Perplexity) against the recorded visitor IP, on a periodic best-effort
sweep — NEVER on the ingest hot path (``routers/events.py`` must never import
this module; see Phase 4 Step F).

Anthropic (Claude) publishes no IP ranges and must NEVER exceed ``ua-only``
confidence, structurally: no ``anthropic.json`` dataset entry exists, so
``verify_ip`` returns ``None`` for it without any vendor-name special case.

Fail-open at three levels (Resolved Design Decision 7):
  a) ``load_ip_ranges`` returns ``{}`` on any file-read/parse error (never raises).
  b) ``verify_ip`` returns ``None`` on any malformed ip/cidr input (never raises).
  c) ``run_verification_sweep`` wraps each row in its own try/except so one bad
     row never aborts the sweep.

No caching (Resolved Design Decision 11): the datasets are two tiny JSON files
and the sweep runs at most every 15 minutes, so ``load_ip_ranges`` reads fresh
from disk on every call. This avoids stale-cache bugs between unit tests that
flip ``settings.mock_external_apis``.
"""

import ipaddress
import json
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.config import settings
from apps.api.models.agent_visit import AgentVisit
from apps.api.services.agent_visit_persistence import upgrade_verification_method

logger = structlog.get_logger()

# Vendors with a published static CIDR dataset. Anthropic is intentionally
# absent — its absence IS the structural ceiling (never exceeds ua-only).
_VENDORS: tuple[str, ...] = ("openai", "perplexity")

# Directory holding ``{vendor}.json`` (real) and ``mock/{vendor}.json`` (mock).
_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "agent_ip_ranges"

# Sweep query sizing (Resolved Design Decision 5).
_SWEEP_WINDOW_DAYS = 7
_SWEEP_BATCH_LIMIT = 500


def load_ip_ranges() -> dict[str, list[str]]:
    """Return ``{vendor: [CIDR, ...]}`` from the static dataset. Fail-open.

    Reads the ``mock/`` subdirectory when ``settings.mock_external_apis`` is
    true, otherwise the real dataset. Any missing file, JSON parse error, or
    malformed shape for a vendor is skipped (logged, never raised); a total
    failure yields ``{}``. Read fresh every call — no caching.
    """
    base = _DATA_DIR / "mock" if settings.mock_external_apis else _DATA_DIR
    ranges: dict[str, list[str]] = {}
    for vendor in _VENDORS:
        path = base / f"{vendor}.json"
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            cidrs = data.get("ranges")
            if isinstance(cidrs, list) and all(isinstance(c, str) for c in cidrs):
                ranges[vendor] = cidrs
            else:
                logger.warning("agent_ip_ranges_malformed", vendor=vendor)
        except FileNotFoundError:
            logger.warning("agent_ip_ranges_missing", vendor=vendor)
        except Exception as exc:
            logger.warning("agent_ip_ranges_load_failed", vendor=vendor, error=str(exc))
    return ranges


def verify_ip(vendor: str, ip: str) -> str | None:
    """Return ``"ip-verified"`` if ``ip`` is within any CIDR for ``vendor``.

    Pure aside from calling ``load_ip_ranges`` internally. A vendor with no
    loaded ranges (including Anthropic) always returns ``None``. Malformed ``ip``
    or CIDR values return ``None`` — never raise (fail-open).
    """
    ranges = load_ip_ranges()
    cidrs = ranges.get(vendor)
    if not cidrs:
        return None
    try:
        addr = ipaddress.ip_address(ip)
    except (ValueError, TypeError):
        return None
    for cidr in cidrs:
        try:
            if addr in ipaddress.ip_network(cidr, strict=False):
                return "ip-verified"
        except (ValueError, TypeError):
            continue
    return None


async def run_verification_sweep(db: AsyncSession) -> None:
    """Upgrade eligible ``ua-only`` agent visits to ``ip-verified``. Fail-open.

    Queries recently-active ``ua-only`` rows for the two vendors with a dataset,
    bounded and cheap (7-day window, 500-row cap). Each row's processing is
    isolated in its own try/except so one bad row never aborts the sweep.
    """
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(days=_SWEEP_WINDOW_DAYS)
    result = await db.execute(
        select(AgentVisit)
        .where(
            AgentVisit.verification_method == "ua-only",
            AgentVisit.vendor.in_(_VENDORS),
            AgentVisit.last_seen_at > cutoff,
        )
        .order_by(AgentVisit.last_seen_at.desc())
        .limit(_SWEEP_BATCH_LIMIT)
    )
    rows = result.scalars().all()
    for row in rows:
        try:
            if not row.ip_address:
                continue
            method = verify_ip(row.vendor, row.ip_address)
            if method:
                await upgrade_verification_method(db, row.id, method)
        except Exception:
            # Per-row fail-open (Resolved Design Decision 7c): log keys only.
            logger.exception("agent_verification_row_failed", id=str(row.id), vendor=row.vendor)
