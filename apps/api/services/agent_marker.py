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

import re
import uuid
from urllib.parse import parse_qs, urlsplit, urlunsplit

import structlog
from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

# Single source of Fernet key handling for the whole app — deliberately reused
# rather than re-implemented, so key parsing and the "unconfigured key" fallback
# cannot drift between the email link decorator and this module.
from apps.api.models.agent_fetch_event import AgentFetchEvent
from apps.api.models.agent_handoff_link import AgentHandoffLink
from apps.api.services.link_decorator import _get_fernet

logger = structlog.get_logger()

# Query parameter carrying the marker. Read server-side off the pageview URL the
# pixel already sends, exactly like the campaign ``_tp`` parameter — no tracker
# change is involved in capturing it.
MARKER_PARAM = "_bam"
# The EDGE-minted sibling. Stamped onto same-host links by the Cloudflare Pages
# middleware, which has neither an ``agent_fetch_events`` row nor the encryption
# key at the moment it must rewrite the HTML — so it cannot mint a ``_bam`` and
# uses its own opaque token instead. Kept as a separate name on purpose: handing
# the ``_bam`` decoder a value it cannot decrypt would look like tampering.
EDGE_MARKER_PARAM = "_bfm"
# What the edge actually mints: lowercase hex, 12 chars today, bounded by the
# 32-char column. Anchored via fullmatch at the call site.
_EDGE_MARKER_RE = re.compile(r"[0-9a-f]{1,32}")

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


def decode_marker_with_reason(token: str | None) -> tuple[uuid.UUID | None, str]:
    """Decode a marker, and say WHY when it fails.

    The reason is what makes a zero-link dashboard diagnosable. ``expired`` and
    ``invalid`` are the same ``InvalidToken`` to Fernet but mean opposite things
    operationally — an expired marker proves the whole chain works and the click
    was simply old, while an invalid one means the token was forged, truncated by
    something in the middle, or minted under a different key. Collapsing them
    would hide which of those is happening.

    Reasons: ``ok`` / ``absent`` / ``no_key`` / ``expired`` / ``invalid`` /
    ``malformed`` (decrypted cleanly but the plaintext was not a UUID).
    """
    if not token:
        return None, "absent"
    fernet = _get_fernet()
    if fernet is None:
        return None, "no_key"
    try:
        raw = fernet.decrypt(token.encode("ascii"), ttl=MARKER_TTL_SECONDS)
    except InvalidToken:
        # Retry without the age limit, on the failure path only. A token that
        # decrypts now had a valid signature all along, so only its age failed.
        try:
            fernet.decrypt(token.encode("ascii"))
            return None, "expired"
        except Exception:
            return None, "invalid"
    except Exception:
        logger.warning("agent_marker_decode_failed")
        return None, "invalid"
    try:
        return uuid.UUID(raw.decode("utf-8")), "ok"
    except (ValueError, UnicodeDecodeError):
        return None, "malformed"


def decode_marker(token: str | None) -> uuid.UUID | None:
    """Decrypt a marker back to its fetch-event id, or ``None`` if unusable.

    Never raises: this runs on the ingest path, where a bad marker must degrade
    to "no deterministic link" and nothing else.
    """
    return decode_marker_with_reason(token)[0]


def marker_from_url(url: str | None, param: str = MARKER_PARAM) -> str | None:
    """Pull a link marker out of a landing URL. Mirrors ``events._tp_from_url``.

    ``param`` defaults to the API-minted ``_bam``; pass ``EDGE_MARKER_PARAM`` for
    the edge-minted one. The substring pre-check is not just a fast path — it is
    what keeps the common case (a landing URL with no marker at all) from paying
    for a full query parse on the ingest hot path.
    """
    if not url or param + "=" not in url:
        return None
    try:
        values = parse_qs(urlsplit(url).query).get(param)
        return values[0] if values else None
    except Exception:
        return None


def edge_marker_from_url(url: str | None) -> str | None:
    """Extract and shape-check the EDGE-minted ``_bfm`` marker from a landing URL.

    Distinct from ``marker_from_url``'s default in both origin and meaning:
    ``_bam`` is this API's own encrypted ``agent_fetch_events`` id, while
    ``_bfm`` is an opaque token a Cloudflare Pages middleware minted on its own —
    it decodes to nothing here and is only ever matched against
    ``AgentFetchEvent.link_marker``, which the same edge reported via the beacon.

    The shape check exists because this value is attacker-controllable: anyone
    can append ``?_bfm=<anything>`` to a link. Storing only what the edge could
    plausibly have minted keeps junk out of the column and keeps the partial
    index selective. A rejected value degrades to "no deterministic link" — the
    same outcome as a visitor who simply arrived without one.

    Never raises: this runs on the ingest path.
    """
    raw = marker_from_url(url, EDGE_MARKER_PARAM)
    if raw is None or not _EDGE_MARKER_RE.fullmatch(raw):
        return None
    return raw


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

    The decoded fetch MUST belong to the site reporting the click, and that is
    checked against the database rather than assumed. Decoding only proves the
    marker was minted by this deployment, not that it was minted for this tenant:
    without the check, a marker lifted from one site's public offers feed and
    replayed on another site's page would file a link under the second site
    pointing at the first site's fetch — and because one fetch may hold only one
    link, it would also permanently occupy the slot the owning site's own click
    needed. Same rule the correlation sweep enforces (AC-H2-5).

    A marker link REPLACES an existing temporal one for the same fetch: the
    sweep's match is a probabilistic guess and this is the ground truth it was
    approximating. It never replaces another marker link — the first real click
    wins, which is what keeps a shared or forwarded link from re-attributing the
    fetch to whoever clicked last.
    """
    fetch_event_id, reason = decode_marker_with_reason(marker)
    if fetch_event_id is not None:
        # Wrapped like every other statement here: this runs on the ingest hot
        # path, so a database hiccup during the check must cost the link, never
        # the pageview. Unverified means not written — the temporal sweep is
        # still free to make its own match later.
        try:
            owns_fetch = (
                await db.execute(
                    select(AgentFetchEvent.id)
                    .where(
                        AgentFetchEvent.id == fetch_event_id,
                        AgentFetchEvent.site_id == site_id,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if owns_fetch is None:
                # Decoded fine, but names another tenant's fetch (or one that no
                # longer exists — retention purges these at 90 days).
                fetch_event_id, reason = None, "foreign_site"
        except Exception:
            await db.rollback()
            logger.warning("agent_marker_ownership_check_failed", site_id=site_id)
            fetch_event_id, reason = None, "check_failed"
    # Always logged, including the boring success. A marker that arrived and
    # decoded is the ONLY evidence that AI surfaces preserve the query parameter
    # at all; without this line, "no links" and "no clicks ever carried a marker"
    # are indistinguishable without reading the database by hand. Keys only —
    # never the marker itself (it is a token) and never a full visitor id.
    logger.info(
        "agent_marker_seen",
        site_id=site_id,
        decoded=fetch_event_id is not None,
        reason=reason,
        visitor_id=visitor_id[:8],
    )
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
        # written=False here is NOT an error: the guard held because this fetch
        # already carries a marker link, i.e. someone else clicked the shared
        # link first. Logged at info so that expected case stays visible and is
        # never mistaken for a silent failure.
        logger.info(
            "agent_marker_handoff_written",
            site_id=site_id,
            written=written,
            visitor_id=visitor_id[:8],
        )
        return written
    except Exception:
        # Keys only — never the marker, never the visitor id.
        await db.rollback()
        logger.warning("agent_marker_handoff_write_failed", site_id=site_id)
        return False
