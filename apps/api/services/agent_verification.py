"""IP-range verification for recognized AI-agent visits (EvalLayer Phase 4).

Judges an agent-visit's recorded IP against published vendor CIDR ranges
(OpenAI, Perplexity) on a periodic best-effort sweep — NEVER on the ingest hot
path (``routers/events.py`` must never import this module; see Phase 4 Step F).

The sweep produces one of three verdicts (see ``verify_ip``): ``ip-verified``,
``ip-mismatch``, or no conclusion. ``ip-mismatch`` is what a forged User-Agent
looks like: the UA claims a vendor that publishes ranges, and the traffic came
from outside all of them.

**A mismatch is recorded, not acted on.** It does not block the visit, does not
delete it, does not touch emailability, and does not exclude the row from
handoff correlation. The published range datasets are the weak link — they go
stale between refreshes and a real agent on a newly-added range would be
labelled a mismatch through no fault of its own. Enforcing on that would drop
legitimate agents silently, which is worse than the problem. Excluding
mismatches from correlation is the natural next step, but only once the refresh
has been observed to keep the datasets complete.

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
from apps.api.services.agent_ip_range_refresh import (
    PUBLISHED_RANGE_SOURCES,
    _RUNTIME_DIR,
)
from apps.api.services.agent_visit_persistence import set_verification_method

logger = structlog.get_logger()

# Agent tokens with a published CIDR dataset, one file each. Keyed per AGENT,
# not per vendor: OpenAI publishes GPTBot, OAI-SearchBot and ChatGPT-User as
# three separate documents with different ranges, and merging them would hide
# GPTBot showing up on ChatGPT-User's range — an anomaly that only remains
# visible while the sets are kept apart.
#
# Every Anthropic token is intentionally absent: Anthropic publishes no ranges,
# so its visits can never be judged either way. That absence IS the ceiling.
_AGENT_TOKENS: tuple[str, ...] = tuple(PUBLISHED_RANGE_SOURCES)

# Directory holding ``{vendor}.json`` (real) and ``mock/{vendor}.json`` (mock).
_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "agent_ip_ranges"

# Sweep query sizing (Resolved Design Decision 5).
_SWEEP_WINDOW_DAYS = 7
_SWEEP_BATCH_LIMIT = 500


def load_ip_ranges() -> dict[str, list[str]]:
    """Return ``{agent_token: [CIDR, ...]}`` from the datasets. Fail-open.

    Reads the ``mock/`` subdirectory when ``settings.mock_external_apis`` is
    true, otherwise the live dataset kept fresh by
    ``agent_ip_range_refresh``. Any missing file, JSON parse error, or malformed
    shape is skipped (logged, never raised); a total failure yields ``{}``, which
    makes every verdict "no conclusion" rather than a wrong one.

    An empty range list is dropped rather than stored: an agent with no usable
    ranges must produce no conclusion, never a mismatch.

    Read fresh every call — no caching. The files are small, the sweep is
    periodic, and a cache would serve pre-refresh data to the sweep that runs
    right after a refresh.
    """
    if settings.mock_external_apis:
        bases = [_DATA_DIR / "mock"]
    else:
        # Runtime output first, shipped placeholder second. The refresh job
        # writes only to ``runtime/`` (it must not dirty git-tracked files), so
        # a token it has fetched is read from there; a token it has never
        # fetched falls through to the shipped file, which is empty by design
        # and therefore yields no verdict rather than a stale one.
        bases = [_RUNTIME_DIR, _DATA_DIR]
    ranges: dict[str, list[str]] = {}
    for token in _AGENT_TOKENS:
        path = next(
            (p for p in ((b / f"{token}.json") for b in bases) if p.is_file()),
            bases[0] / f"{token}.json",
        )
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            cidrs = data.get("ranges")
            if isinstance(cidrs, list) and all(isinstance(c, str) for c in cidrs):
                if cidrs:
                    ranges[token] = cidrs
            else:
                logger.warning("agent_ip_ranges_malformed", agent=token)
        except FileNotFoundError:
            logger.warning("agent_ip_ranges_missing", agent=token)
        except Exception as exc:
            logger.warning("agent_ip_ranges_load_failed", agent=token, error=str(exc))
    return ranges


def verify_ip(agent_token: str, ip: str) -> str | None:
    """Judge ``ip`` against the published CIDRs for one agent token.

    Three outcomes, and the difference between the last two is the whole point:

    - ``"ip-verified"`` — the IP falls inside a published range.
    - ``"ip-mismatch"`` — the vendor publishes ranges and the IP is in none of
      them. The User-Agent claims to be this agent while the traffic did not
      come from its published ranges, which is what a forged UA looks like.
    - ``None`` — no conclusion is possible: the agent publishes nothing
      (every Anthropic token), the dataset has not been fetched yet, or the IP
      is unusable. Never inferred as a mismatch, because "we cannot check" and
      "we checked and it failed" are different facts and collapsing them would
      invent evidence.

    Pure aside from calling ``load_ip_ranges`` internally. Never raises.
    """
    ranges = load_ip_ranges()
    cidrs = ranges.get(agent_token)
    if not cidrs:
        return None
    try:
        addr = ipaddress.ip_address(ip)
    except (ValueError, TypeError):
        return None
    checked_any = False
    for cidr in cidrs:
        try:
            network = ipaddress.ip_network(cidr, strict=False)
        except (ValueError, TypeError):
            continue
        checked_any = True
        if addr in network:
            return "ip-verified"
    # Only a dataset that actually parsed can support a mismatch verdict; if
    # every CIDR was malformed nothing was really checked.
    return "ip-mismatch" if checked_any else None


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
            AgentVisit.product_or_ua_token.in_(_AGENT_TOKENS),
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
            method = verify_ip(row.product_or_ua_token, row.ip_address)
            if method:
                await set_verification_method(db, row.id, method)
        except Exception:
            # Per-row fail-open (Resolved Design Decision 7c): log keys only.
            logger.exception(
                "agent_verification_row_failed",
                id=str(row.id),
                agent=row.product_or_ua_token,
            )
