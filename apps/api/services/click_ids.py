"""Pure ad click-id extraction from an event URL (conversion-apis AC-1).

The pixel already sends the full page URL (``events.url``), query string
included, so click ids are parsed server-side — no tracker.js change.
"""

from urllib.parse import parse_qs, urlsplit

CLICK_ID_PARAMS = ("fbclid", "gclid", "wbraid", "gbraid", "li_fat_id")

# Postgres regex used by the aggregator to pre-filter events whose URL carries
# at least one NON-EMPTY click-id param. Kept beside the parser so both agree.
CLICK_ID_URL_REGEX = r"[?&](fbclid|gclid|wbraid|gbraid|li_fat_id)=[^&#]"

_MAX_VALUE_LEN = 500


def extract_click_ids(url: str | None) -> dict[str, str]:
    """Return ``{param: value}`` for each click-id param present and non-empty.

    Only the first value of a repeated param is kept. Never raises: a malformed
    URL yields ``{}``. Values are stripped and length-capped.
    """
    if not url or not isinstance(url, str):
        return {}
    try:
        query = urlsplit(url.strip()).query
        parsed = parse_qs(query, keep_blank_values=False)
    except ValueError:
        return {}
    out: dict[str, str] = {}
    for key in CLICK_ID_PARAMS:
        values = parsed.get(key)
        if not values:
            continue
        value = (values[0] or "").strip()
        if value:
            out[key] = value[:_MAX_VALUE_LEN]
    return out


def build_visitor_click_ids(url: str | None, event_created_at_ms: int) -> dict | None:
    """Click ids to persist on ``visitors.click_ids`` — or None when none.

    ``fbc_ts`` (epoch-ms ``created_at`` of the click-id event) is added only
    when an ``fbclid`` is present; it feeds Meta's ``fbc`` =
    ``fb.1.{fbc_ts}.{fbclid}``.
    """
    ids = extract_click_ids(url)
    if not ids:
        return None
    result: dict = dict(ids)
    if "fbclid" in ids:
        result["fbc_ts"] = int(event_created_at_ms)
    return result


def meta_fbc(click_ids: dict | None) -> str | None:
    """Meta ``fbc`` value from stored click ids, or None."""
    if not click_ids or not click_ids.get("fbclid") or click_ids.get("fbc_ts") is None:
        return None
    return f"fb.1.{int(click_ids['fbc_ts'])}.{click_ids['fbclid']}"


def google_ad_identifier(click_ids: dict | None) -> tuple[str, str] | None:
    """Exactly one Google click id by priority gclid > wbraid > gbraid."""
    if not click_ids:
        return None
    for key in ("gclid", "wbraid", "gbraid"):
        if click_ids.get(key):
            return key, click_ids[key]
    return None
