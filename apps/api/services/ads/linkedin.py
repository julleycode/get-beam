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
