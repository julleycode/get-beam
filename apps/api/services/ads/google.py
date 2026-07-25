"""Google Customer Match provider.

PHASE 1 SCOPE: stub only. Deterministic under ``settings.mock_external_apis``;
raises NotImplementedError otherwise (router wraps into HTTP 501). Real Google
Ads API wiring lands in Phase 3.
"""

import uuid

from apps.api.config import settings
from apps.api.services.ads.base import (
    AdOAuthTokens,
    AdsProvider,
    AdTestOutcome,
    AudienceResult,
    HashedContact,
)


class GoogleAdsProvider(AdsProvider):
    provider = "google"

    async def get_oauth_url(self, state: str) -> str:
        if settings.mock_external_apis:
            return f"https://mock.google.test/o/oauth2/auth?state={state}"
        # PHASE 3: build the real Google OAuth consent URL from
        # settings.google_ads_client_id / google_ads_redirect_uri + adwords scope.
        raise NotImplementedError("Google Customer Match is not implemented yet")

    async def exchange_code(self, code: str, state: str = "") -> AdOAuthTokens:
        if settings.mock_external_apis:
            return AdOAuthTokens(
                access_token=f"mock-google-token-{uuid.uuid4().hex}",
                refresh_token=f"mock-google-refresh-{uuid.uuid4().hex}",
                scopes=["https://www.googleapis.com/auth/adwords"],
                external_account_id="mock-google-account",
                external_account_label="Google Customer Match (mock)",
                ad_account_id="123-456-7890",
            )
        # PHASE 3: exchange at oauth2.googleapis.com/token.
        raise NotImplementedError("Google Customer Match is not implemented yet")

    async def test_connection(self, connection) -> AdTestOutcome:
        if settings.mock_external_apis:
            return AdTestOutcome(is_valid=True, message="Connection is live (mock)")
        # PHASE 3: listAccessibleCustomers to confirm the token still works.
        raise NotImplementedError("Google Customer Match is not implemented yet")

    async def create_or_update_audience(
        self, connection, link, hashed_contacts: list[HashedContact]
    ) -> AudienceResult:
        if settings.mock_external_apis:
            audience_id = (
                getattr(link, "platform_audience_id", "")
                or f"mock-google-aud-{uuid.uuid4().hex}"
            )
            return AudienceResult(
                platform_audience_id=audience_id, pushed=len(hashed_contacts)
            )
        # PHASE 3: UserListService create + OfflineUserDataJobService upload.
        raise NotImplementedError("Google Customer Match is not implemented yet")
