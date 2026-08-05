"""Identity-graph record matching, shared by Leadpipe and Capturify.

A provider record may only be attached to a visitor when its IP matches AND it
was captured within a recency window of the visitor's own activity. Moved
verbatim from identity_resolver.py.
"""

from datetime import datetime, timedelta, timezone

import structlog

from apps.api.models.visitor import Visitor

logger = structlog.get_logger()

# Why a candidate record was refused. Every rejection is tallied under one of
# these so "the provider returned rows but none attached" stops being invisible —
# previously two of the three only surfaced as scattered per-record log lines and
# `ip_mismatch` sat at `debug`, which production logging drops entirely.
REJECTION_NO_TIMESTAMP = "no_timestamp"
REJECTION_OUTSIDE_WINDOW = "outside_window"
REJECTION_IP_MISMATCH = "ip_mismatch"
REJECTION_NO_EMAIL = "no_email"

REJECTION_REASONS = (
    REJECTION_NO_TIMESTAMP,
    REJECTION_OUTSIDE_WINDOW,
    REJECTION_IP_MISMATCH,
    REJECTION_NO_EMAIL,
)


def new_rejection_tally() -> dict[str, int]:
    """A zeroed tally so every reason reports explicitly, including 0."""
    return {reason: 0 for reason in REJECTION_REASONS}


def log_rejection_tally(provider: str, visitor_id: str, tally: dict[str, int], scanned: int) -> None:
    """Emit one countable summary per provider scan.

    Logged at `info` so it survives production log levels, and only when the scan
    actually rejected something — a clean scan should not add noise.

    `rejected` is reported alongside `scanned` so the two reconcile: every record
    the caller looked at is either tallied under a reason or was a match. A gap
    between them means a silent `continue` was added without a reason.
    """
    if not any(tally.values()):
        return
    logger.info(
        "identity_graph_records_rejected",
        provider=provider,
        visitor_id=visitor_id[:8],
        scanned=scanned,
        rejected=sum(tally.values()),
        **tally,
    )


def _bump(tally: dict[str, int] | None, reason: str) -> None:
    if tally is not None:
        tally[reason] = tally.get(reason, 0) + 1


class MatchingMixin:
    # A provider record may only be attached to a visitor when its IP matches
    # AND it was captured within this window of the visitor's own activity.
    # Identity-graph feeds are account-wide (latest N identifications across
    # ALL traffic), so bare IP equality risks attaching the wrong human —
    # e.g. CGNAT/office IPs shared by many people across hours or days.
    _IDENTITY_MATCH_WINDOW = timedelta(minutes=30)

    # Field-name variants providers use for the record capture timestamp
    # (same flexible-variant style as the ip/ipAddress/ip_address handling).
    _RECORD_TIMESTAMP_FIELDS = (
        "timestamp",
        "capturedAt",
        "captured_at",
        "createdAt",
        "created_at",
        "identifiedAt",
        "identified_at",
        "lastSeen",
        "last_seen",
        "seenAt",
        "seen_at",
        "visitedAt",
        "visited_at",
        "date",
    )

    # Confidence ceiling for IP-only matches (no record timestamp available)
    _WEAK_MATCH_MAX_CONFIDENCE = 0.6

    @classmethod
    def _parse_record_timestamp(cls, record: dict) -> datetime | None:
        """Best-effort parse of an identification record's capture time (UTC).

        Accepts ISO-8601 strings (with or without 'Z'/offset) and epoch
        seconds/milliseconds. Returns a timezone-aware UTC datetime, or None
        when no usable timestamp field exists on the record.
        """
        for field in cls._RECORD_TIMESTAMP_FIELDS:
            raw = record.get(field)
            if raw is None or isinstance(raw, bool):
                continue
            if isinstance(raw, (int, float)):
                ts = float(raw)
                if ts > 1e12:  # epoch milliseconds
                    ts /= 1000.0
                try:
                    return datetime.fromtimestamp(ts, tz=timezone.utc)
                except (OverflowError, OSError, ValueError):
                    continue
            if isinstance(raw, str) and raw.strip():
                try:
                    parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
                except ValueError:
                    continue
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
        return None

    @staticmethod
    def _visitor_activity_utc(visitor: Visitor) -> datetime:
        """The visitor's most recent activity as an aware UTC datetime.

        Visitor.last_seen is stored naive-UTC; fall back to "now" if missing.
        """
        last_seen = getattr(visitor, "last_seen", None)
        if isinstance(last_seen, datetime):
            if last_seen.tzinfo is None:
                return last_seen.replace(tzinfo=timezone.utc)
            return last_seen.astimezone(timezone.utc)
        return datetime.now(timezone.utc)

    def _record_matches_visitor(
        self,
        record: dict,
        visitor: Visitor,
        provider: str,
        *,
        tally: dict[str, int] | None = None,
    ) -> tuple[bool, bool]:
        """Decide whether an identity-graph record belongs to this visitor.

        Returns (matched, weak):
          - (False, False): record is not this visitor — IP mismatch, OR no
            usable timestamp (IP equality alone is refused), OR timestamped
            outside the recency window. Caller must skip it.
          - (True, False):  IP matches AND record timestamp is within
            _IDENTITY_MATCH_WINDOW of the visitor's activity — strong match.
          - (True, True):   no longer produced — IP-only matches are refused.

        Pass `tally` (from `new_rejection_tally()`) to count why records were
        refused; without it the behavior is unchanged.
        """
        record_ts = self._parse_record_timestamp(record)
        if record_ts is None:
            # No usable timestamp → IP equality ALONE is not enough to attach an
            # identity. Identity-graph feeds are account-wide and office/CGNAT
            # IPs are shared by many people, so a timestamp-less record could be
            # anyone who shared that IP. Refuse rather than save a likely-wrong
            # person at low confidence.
            _bump(tally, REJECTION_NO_TIMESTAMP)
            logger.info(
                "identity_graph_record_no_timestamp_skipped",
                provider=provider,
                visitor_id=visitor.visitor_id[:8],
                reason=REJECTION_NO_TIMESTAMP,
            )
            return (False, False)

        delta = abs(record_ts - self._visitor_activity_utc(visitor))
        if delta > self._IDENTITY_MATCH_WINDOW:
            _bump(tally, REJECTION_OUTSIDE_WINDOW)
            logger.info(
                "identity_graph_record_outside_window",
                provider=provider,
                visitor_id=visitor.visitor_id[:8],
                delta_minutes=int(delta.total_seconds() // 60),
                reason=REJECTION_OUTSIDE_WINDOW,
            )
            return (False, False)
        return (True, False)
