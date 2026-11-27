"""LinkedIn Matched Audiences provider — permanently a stub.

LinkedIn's Matched Audiences API is not open to us, so this module exists only
so the registry pattern is uniform across all three providers. Readiness is
enforced at the router/schema layer via ``READY["linkedin"] = False`` (see
services/ads/base.py) — this class is never reachable through the connect
endpoint. The LinkedIn CSV export path (services/csv_exporter.py) is
unaffected and remains the supported LinkedIn workflow.
"""

from apps.api.services.ads.base import (
    AdOAuthTokens,
    AdsProvider,
    AdTestOutcome,
    AudienceResult,
    HashedContact,
)

_UNSUPPORTED = "LinkedIn Matched Audiences is not supported — use the CSV export"


class LinkedInAdsProvider(AdsProvider):
    provider = "linkedin"

    async def get_oauth_url(self, state: str) -> str:
        raise NotImplementedError(_UNSUPPORTED)

    async def exchange_code(self, code: str, state: str = "") -> AdOAuthTokens:
        raise NotImplementedError(_UNSUPPORTED)

    async def test_connection(self, connection) -> AdTestOutcome:
        raise NotImplementedError(_UNSUPPORTED)

    async def create_or_update_audience(
        self, connection, link, hashed_contacts: list[HashedContact]
    ) -> AudienceResult:
        raise NotImplementedError(_UNSUPPORTED)


def build_linkedin_seed_csv(contacts: list[HashedContact]) -> str:
    """closed-won-lookalikes: hashed seed for manual Matched Audiences upload."""
    lines = ["email_sha256"] + [c.email_sha256 for c in contacts if c.email_sha256]
    return "\n".join(lines) + "\n"


# ── conversion-apis: LinkedIn offline-conversion CSV export (v1, CSV-only) ──

LINKEDIN_CONVERSION_CSV_COLUMNS = (
    "email_sha256",
    "li_fat_id",
    "conversion_type",
    "event_name",
    "event_time",
    "dedup_id",
)


def build_linkedin_conversions_csv(events) -> str:
    """CSV of hashed conversions for manual LinkedIn upload. No plaintext PII."""
    import csv
    import io
    from datetime import timezone

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(LINKEDIN_CONVERSION_CSV_COLUMNS)
    for e in events:
        when = e.event_time
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        writer.writerow(
            [
                e.email_sha256,
                (e.click_ids or {}).get("li_fat_id", ""),
                e.conversion_type,
                e.event_name,
                when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                e.dedup_id,
            ]
        )
    return buf.getvalue()
