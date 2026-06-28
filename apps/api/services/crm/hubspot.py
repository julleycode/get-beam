"""HubSpot connector — OAuth + Contacts batch upsert (idempotent on email)."""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import structlog

from apps.api.config import settings
from apps.api.services.crm.base import (
    HTTP_TIMEOUT,
    CRMContact,
    CRMConnector,
    CrmOAuthTokens,
    PushResult,
    _http_retry,
    sanitize_error,
)

logger = structlog.get_logger()

_AUTH_URL = "https://app.hubspot.com/oauth/authorize"
_TOKEN_URL = "https://api.hubapi.com/oauth/v1/token"
_CONTACTS_URL = "https://api.hubapi.com/crm/v3/objects/contacts"
_BATCH_UPSERT_URL = "https://api.hubapi.com/crm/v3/objects/contacts/batch/upsert"
_SCOPES = "crm.objects.contacts.write crm.objects.contacts.read"
_BATCH_SIZE = 100  # HubSpot batch limit

# CRMContact attr → HubSpot contact property name.
_PROPERTY_MAP = {
    "first_name": "firstname",
    "last_name": "lastname",
    "phone": "phone",
    "company_name": "company",
    "job_title": "jobtitle",
    "city": "city",
    "region": "state",
    "country": "country",
}


def _to_properties(contact: CRMContact) -> dict:
    props = {"email": contact.email}
    for attr, hs_prop in _PROPERTY_MAP.items():
        value = getattr(contact, attr, "")
        if value:
            props[hs_prop] = value
    return props


class HubSpotConnector(CRMConnector):
    provider = "hubspot"
    auth_type = "oauth"

    async def get_auth_url(self, state: str) -> str:
        params = {
            "client_id": settings.hubspot_client_id,
            "redirect_uri": settings.hubspot_redirect_uri,
            "scope": _SCOPES,
            "state": state,
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    @_http_retry
    async def _token_request(self, data: dict) -> dict:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(_TOKEN_URL, data=data)
        resp.raise_for_status()
        return resp.json()

    def _tokens_from_payload(self, payload: dict) -> CrmOAuthTokens:
        expires_in = int(payload.get("expires_in", 0) or 0)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in) if expires_in else None
        )
        return CrmOAuthTokens(
            access_token=payload.get("access_token", ""),
            refresh_token=payload.get("refresh_token"),
            expires_at=expires_at,
            scopes=_SCOPES.split(),
            external_account_label="HubSpot",
        )

    async def exchange_code(self, code: str, state: str = "") -> CrmOAuthTokens:
        if settings.mock_external_apis:
            return CrmOAuthTokens(
                access_token="mock_hubspot_token",
                refresh_token="mock_hubspot_refresh",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=6),
                external_account_label="HubSpot (mock)",
            )
        payload = await self._token_request(
            {
                "grant_type": "authorization_code",
                "client_id": settings.hubspot_client_id,
                "client_secret": settings.hubspot_client_secret,
                "redirect_uri": settings.hubspot_redirect_uri,
                "code": code,
            }
        )
        return self._tokens_from_payload(payload)

    async def refresh_tokens(self, refresh_token: str) -> CrmOAuthTokens:
        if settings.mock_external_apis:
            return CrmOAuthTokens(
                access_token="mock_hubspot_token",
                refresh_token=refresh_token,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=6),
                external_account_label="HubSpot (mock)",
            )
        payload = await self._token_request(
            {
                "grant_type": "refresh_token",
                "client_id": settings.hubspot_client_id,
                "client_secret": settings.hubspot_client_secret,
                "refresh_token": refresh_token,
            }
        )
        tokens = self._tokens_from_payload(payload)
        # HubSpot may not echo the refresh token on refresh — keep the old one.
        if not tokens.refresh_token:
            tokens.refresh_token = refresh_token
        return tokens

    async def test_connection(
        self,
        *,
        access_token: str = "",
        webhook_url: str = "",
        secret: str = "",
        instance_url: str = "",
    ) -> bool:
        if settings.mock_external_apis:
            return True
        if not access_token:
            return False
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                resp = await client.get(
                    _CONTACTS_URL,
                    params={"limit": 1},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            return resp.status_code == 200
        except httpx.HTTPError as exc:
            logger.warning("crm_hubspot_test_failed", error=sanitize_error(exc))
            return False

    @_http_retry
    async def _batch_upsert(self, access_token: str, inputs: list[dict]) -> None:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(
                _BATCH_UPSERT_URL,
                json={"inputs": inputs},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
            )
        resp.raise_for_status()

    async def upsert_contacts(
        self,
        contacts: list[CRMContact],
        *,
        access_token: str = "",
        webhook_url: str = "",
        secret: str = "",
        instance_url: str = "",
    ) -> PushResult:
        if settings.mock_external_apis:
            return PushResult(pushed=len(contacts), failed=0, errors=[])
        if not access_token:
            return PushResult(pushed=0, failed=len(contacts), errors=["HubSpot not connected"])

        pushed = 0
        failed = 0
        errors: list[str] = []
        for start in range(0, len(contacts), _BATCH_SIZE):
            batch = contacts[start : start + _BATCH_SIZE]
            inputs = [
                {"idProperty": "email", "id": c.email, "properties": _to_properties(c)}
                for c in batch
            ]
            try:
                await self._batch_upsert(access_token, inputs)
                pushed += len(batch)
            except httpx.HTTPError as exc:
                failed += len(batch)
                msg = sanitize_error(exc)
                if msg not in errors:
                    errors.append(msg)
                logger.warning("crm_hubspot_push_failed", count=len(batch), error=msg)
        return PushResult(pushed=pushed, failed=failed, errors=errors)
