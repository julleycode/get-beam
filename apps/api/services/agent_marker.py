"""Per-fetch link marker — the deterministic half of handoff detection (F2).

The correlation sweep (``agent_handoff_correlation``) answers "which human is
behind this AI?" by guessing: same site, same vendor family, click within 30
minutes. Two people asking ChatGPT about the same page in one window are
indistinguishable to it, and it cannot tell that it got one wrong.

This module removes the guess for the one path Beam controls end to end. When an
agent pulls ``offers.json``, the fetch is already recorded as an
``agent_fetch_events`` row; its id is encrypted into a marker stamped onto each
offer URL. A human who clicks that link lands on the customer's pixel'd site
carrying the marker, the pixel reports the landing URL as it already does for
every pageview, and the marker decodes back to the exact originating fetch. No
timing, no vendor-family inference.

Three deliberate limits:

- **Only same-host offer URLs are stamped.** A marker on a third-party checkout
  link could never be read back (no Beam pixel there), so stamping one would
  hand out a token for nothing in return.
- **Markers expire.** "Did this human arrive from that agent's answer" stops
  being a meaningful question long before a link stops working, so a stale
  forwarded link decodes to nothing rather than inventing an attribution.
- **A marker identifies a FETCH, never a person.** It is minted before any human
  exists, is identical for everyone who receives that agent's answer, and a
  shared link therefore attributes at most one visitor (the fetch's unique
  constraint on ``agent_handoff_links`` makes first-click-wins structural).

Emailability separation (the program's highest-priority gate): like the sweep,
this module imports ZERO identity/Visitor write path and never touches the
agent-origin emailability marker. A handoff link is attribution metadata; it
makes nobody contactable.
"""

import uuid
from urllib.parse import parse_qs, urlsplit, urlunsplit

import structlog
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

# Single source of Fernet key handling for the whole app — deliberately reused
# rather than re-implemented, so key parsing and the "unconfigured key" fallback
# cannot drift between the email link decorator and this module.
from apps.api.models.agent_handoff_link import AgentHandoffLink
from apps.api.services.link_decorator import _get_fernet

logger = structlog.get_logger()

# Query parameter carrying the marker. Read server-side off the pageview URL the
# pixel already sends, exactly like the campaign ``_tp`` parameter — no tracker
# change is involved in capturing it.
MARKER_PARAM = "_bam"

# A click this long after the fetch is no longer plausibly "the human acting on
# that agent answer" — it is a forwarded or bookmarked link. Fernet stamps a mint
# time into the token, so expiry is enforced at decrypt with no stored state.
MARKER_TTL_SECONDS = 7 * 86400


def mint_marker(fetch_event_id: uuid.UUID | None) -> str | None:
    """Encrypt one ``agent_fetch_events`` id into a URL-safe marker, or ``None``.

    ``None`` whenever a marker cannot be minted — no fetch id (the visit was not
    recorded, e.g. an unrecognized UA) or no configured encryption key. Callers
    then serve an unmarked feed, which is exactly today's behavior.

    Encrypted rather than merely signed so the feed never publishes internal row
    ids, and so a forged marker cannot name a fetch of the attacker's choosing.
    """
    if fetch_event_id is None:
        return None
    fernet = _get_fernet()
    if fernet is None:
        logger.debug("agent_marker_mint_skipped_no_key")
        return None
    try:
        return fernet.encrypt(str(fetch_event_id).encode("utf-8")).decode("ascii")
    except Exception:
        # Keys only — never the token or the id.
        logger.warning("agent_marker_mint_failed")
        return None


def decode_marker(token: str | None) -> uuid.UUID | None:
    """Decrypt a marker back to its fetch-event id. ``None`` if unusable.

    ``None`` covers every failure the same way — absent, malformed, forged,
    expired past ``MARKER_TTL_SECONDS``, or key unconfigured. Never raises: this
    runs on the ingest path, where a bad marker must degrade to "no deterministic
    link" and nothing else.
    """
    if not token:
        return None
    fernet = _get_fernet()
    if fernet is None:
        return None
    try:
        raw = fernet.decrypt(token.encode("ascii"), ttl=MARKER_TTL_SECONDS)
        return uuid.UUID(raw.decode("utf-8"))
    except (InvalidToken, ValueError, UnicodeDecodeError):
        return None
    except Exception:
        logger.warning("agent_marker_decode_failed")
        return None


def marker_from_url(url: str | None) -> str | None:
    """Pull the marker out of a landing URL. Mirrors ``events._tp_from_url``."""
    if not url or MARKER_PARAM + "=" not in url:
        return None
    try:
        values = parse_qs(urlsplit(url).query).get(MARKER_PARAM)
        return values[0] if values else None
    except Exception:
        return None


def _bare_host(netloc: str) -> str:
    """Lowercased host minus userinfo/port and a ``www.`` prefix."""
    host = netloc.lower().split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def stamp_marker(url: str | None, marker: str, site_url: str | None) -> str | None:
    """Append the marker to ``url`` when it points at the site's own host.

    A foreign host is returned untouched: only the customer's own pages run the
    Beam pixel, so a marker anywhere else could never be read back. Existing
    query parameters are preserved, and a URL that already carries a marker is
    left alone.
    """
    if not url or not site_url:
        return url
    try:
        site_host = _bare_host(urlsplit(site_url).netloc)
        parts = urlsplit(url)
        host = _bare_host(parts.netloc)
        if not site_host or not host:
            return url
        if not (host == site_host or host.endswith("." + site_host)):
            return url
        if MARKER_PARAM + "=" in parts.query:
            return url
        query = (parts.query + "&" if parts.query else "") + f"{MARKER_PARAM}={marker}"
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, query, parts.fragment)
        )
    except Exception:
        # A malformed customer-authored URL must not break the feed.
        return url


async def record_marker_handoff(
    db: AsyncSession, *, site_id: str, visitor_id: str, marker: str
) -> bool:
    """Write the deterministic fetch↔visitor link for a marked click.

    Returns True when a link was written or upgraded. Fail-open and quiet: a
    marker that does not decode, or any write failure, simply yields no link —
    the temporal sweep still runs and the pageview itself is unaffected.

    Site-scoped on the way in (the link is only written under the site that
    served the click) so a marker replayed against another tenant cannot create a
    cross-site link.

    A marker link REPLACES an existing temporal one for the same fetch: the
    sweep's match is a probabilistic guess and this is the ground truth it was
    approximating. It never replaces another marker link — the first real click
    wins, which is what keeps a shared or forwarded link from re-attributing the
    fetch to whoever clicked last.
    """
    fetch_event_id = decode_marker(marker)
    if fetch_event_id is None:
        return False
    try:
        result = await db.execute(
            pg_insert(AgentHandoffLink)
            .values(
                site_id=site_id,
                visitor_id=visitor_id,
                agent_fetch_event_id=fetch_event_id,
                confidence="high",
                method="marker",
                delta_seconds=0,
                matched_page=None,
            )
            .on_conflict_do_update(
                constraint="uq_agent_handoff_links_fetch_event",
                set_={
                    "visitor_id": visitor_id,
                    "confidence": "high",
                    "method": "marker",
                    "site_id": site_id,
                },
                where=AgentHandoffLink.__table__.c.method != "marker",
            )
            .returning(AgentHandoffLink.id)
        )
        written = result.scalar_one_or_none() is not None
        await db.commit()
        return written
    except Exception:
        # Keys only — never the marker, never the visitor id.
        await db.rollback()
        logger.warning("agent_marker_handoff_write_failed", site_id=site_id)
        return False
