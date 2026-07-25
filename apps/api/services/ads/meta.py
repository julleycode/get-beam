"""Meta Custom Audiences provider.

PHASE 1 SCOPE: stub only. Every method short-circuits deterministically when
``settings.mock_external_apis`` is on, and raises NotImplementedError
otherwise (the router wraps that into a clean HTTP 501 — see routers/ads.py).
Real Graph API wiring lands in Phase 2.
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


class MetaAdsProvider(AdsProvider):
    provider = "meta"

    async def get_oauth_url(self, state: str) -> str:
        if settings.mock_external_apis:
            return f"https://mock.meta.test/dialog/oauth?state={state}"
        # PHASE 2: build the real Facebook OAuth dialog URL from
        # settings.meta_ads_client_id / meta_ads_redirect_uri + ads_management scope.
        raise NotImplementedError("Meta Custom Audiences is not implemented yet")

    async def exchange_code(self, code: str, state: str = "") -> AdOAuthTokens:
        if settings.mock_external_apis:
            return AdOAuthTokens(
                access_token=f"mock-meta-token-{uuid.uuid4().hex}",
                refresh_token=None,
                scopes=["ads_management"],
                external_account_id="mock-meta-account",
                external_account_label="Meta Custom Audiences (mock)",
                ad_account_id="act_mock",
                business_id="mock-business",
            )
        # PHASE 2: exchange the code at graph.facebook.com/oauth/access_token.
        raise NotImplementedError("Meta Custom Audiences is not implemented yet")

    async def test_connection(self, connection) -> AdTestOutcome:
        if settings.mock_external_apis:
            return AdTestOutcome(is_valid=True, message="Connection is live (mock)")
        # PHASE 2: GET /me/adaccounts to confirm the token still works.
        raise NotImplementedError("Meta Custom Audiences is not implemented yet")

    async def create_or_update_audience(
        self, connection, link, hashed_contacts: list[HashedContact]
    ) -> AudienceResult:
        if settings.mock_external_apis:
            audience_id = (
                getattr(link, "platform_audience_id", "")
                or f"mock-meta-aud-{uuid.uuid4().hex}"
            )
            return AudienceResult(
                platform_audience_id=audience_id, pushed=len(hashed_contacts)
            )
        # PHASE 2: POST /{ad_account_id}/customaudiences then
        # POST /{audience_id}/users with the SHA256 schema payload.
        raise NotImplementedError("Meta Custom Audiences is not implemented yet")
