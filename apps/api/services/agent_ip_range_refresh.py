"""Refresh the published per-agent IP-range datasets used by agent verification.

The datasets that ship in the repo go stale the moment a vendor rotates a range,
and a stale dataset is not a harmless gap: with mismatch detection in place, a
real agent arriving from a newly-published range gets recorded as
``ip-mismatch`` — the same verdict a forged User-Agent gets. Verification is only
as trustworthy as the freshness of what it checks against.

**One file per agent, never merged per vendor.** OpenAI publishes GPTBot,
OAI-SearchBot and ChatGPT-User as three separate documents with different
ranges. Merging them into a single "openai" set would silently destroy the
ability to notice GPTBot arriving from ChatGPT-User's range — an anomaly worth
seeing, and one that only exists as a signal while the sets are kept apart.

Fail-open at every level: a failed fetch, a bad status, unparseable JSON or an
unrecognized shape leaves the existing dataset untouched. A refresh that cannot
improve the data must never destroy it.
"""

import json
from pathlib import Path

import httpx
import structlog

from apps.api.config import settings

logger = structlog.get_logger()

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "agent_ip_ranges"

# Refreshed data is written HERE, never over the shipped files. Those are
# git-tracked and deliberately empty ("empty = no conclusion"); a job that
# overwrites them leaves every developer machine with a permanently dirty
# working tree and turns the test that guards the empty invariant red forever
# after the API is run once. Runtime output belongs outside version control.
# Read back by ``agent_verification.load_ip_ranges``, which prefers this
# directory and falls through to the shipped files when a token has never been
# fetched — so an unfetched agent still yields no verdict rather than a wrong one.
_RUNTIME_DIR = _DATA_DIR / "runtime"

# Agent token -> published range document. Keyed by the same token
# ``agent_classifier`` returns, so verification can look a row up directly by
# what it observed rather than going through a vendor grouping that would blur
# the per-agent distinction.
PUBLISHED_RANGE_SOURCES: dict[str, str] = {
    "gptbot": "https://openai.com/gptbot.json",
    "oai-searchbot": "https://openai.com/searchbot.json",
    "chatgpt-user": "https://openai.com/chatgpt-user.json",
    "perplexitybot": "https://www.perplexity.ai/perplexitybot.json",
    "perplexity-user": "https://www.perplexity.ai/perplexity-user.json",
}

_FETCH_TIMEOUT_SECONDS = 15.0


def normalize_prefixes(payload: object) -> list[str]:
    """Pull CIDR strings out of a published range document.

    The observed shape is ``{"creationTime": ..., "prefixes": [{"ipv4Prefix":
    "..."}, ...]}`` with an ``ipv6Prefix`` variant for v6 entries. A plain
    ``{"ranges": [...]}`` list is also accepted so the stored format round-trips
    through this function unchanged.

    Unknown shapes yield an empty list rather than raising: the caller treats
    empty as "learned nothing" and keeps whatever it already had.
    """
    if not isinstance(payload, dict):
        return []

    ranges = payload.get("ranges")
    if isinstance(ranges, list):
        return [c for c in ranges if isinstance(c, str) and c]

    prefixes = payload.get("prefixes")
    if not isinstance(prefixes, list):
        return []

    out: list[str] = []
    for entry in prefixes:
        if not isinstance(entry, dict):
            continue
        for key in ("ipv4Prefix", "ipv6Prefix"):
            value = entry.get(key)
            if isinstance(value, str) and value:
                out.append(value)
    return out


def _write_dataset(token: str, cidrs: list[str]) -> None:
    path = _RUNTIME_DIR / f"{token}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"agent": token, "ranges": cidrs}, indent=2) + "\n",
        encoding="utf-8",
    )


async def refresh_agent_ip_ranges() -> dict[str, int]:
    """Re-fetch every published dataset. Returns ``{token: cidr_count}``.

    Only tokens that actually produced ranges appear in the result; a source that
    failed or returned nothing usable is logged and skipped, leaving its existing
    file in place. Mock mode short-circuits — the mock datasets are fixtures and
    must not be overwritten by live data.
    """
    if settings.mock_external_apis:
        logger.info("agent_ip_range_refresh_skipped_mock_mode")
        return {}

    updated: dict[str, int] = {}
    async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT_SECONDS) as client:
        for token, url in PUBLISHED_RANGE_SOURCES.items():
            try:
                response = await client.get(url)
                response.raise_for_status()
                cidrs = normalize_prefixes(response.json())
            except Exception as exc:
                # Keep the existing dataset. Log the class only — never the body.
                logger.warning(
                    "agent_ip_range_fetch_failed",
                    agent=token,
                    error=type(exc).__name__,
                )
                continue

            if not cidrs:
                logger.warning("agent_ip_range_empty_payload", agent=token)
                continue

            try:
                _write_dataset(token, cidrs)
            except Exception as exc:
                logger.warning(
                    "agent_ip_range_write_failed",
                    agent=token,
                    error=type(exc).__name__,
                )
                continue

            updated[token] = len(cidrs)

    logger.info("agent_ip_range_refresh_done", **updated)
    return updated
