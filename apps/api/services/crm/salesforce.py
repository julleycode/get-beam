"""Salesforce connector — OAuth + Contact upsert (SOQL lookup then create/update).

Token exchange returns an `instance_url` (e.g. https://yourorg.my.salesforce.com)
which we persist in `external_account_id` and the router passes back as
`instance_url`.

Salesforce Contact requires LastName, so we fall back to the email local-part
when the visitor name is blank. We SOQL-query Contact by Email, then PATCH the
match or POST a new record.
"""

import asyncio
from urllib.parse import urlencode

import httpx
import structlog

from apps.api.config import settings
from apps.api.services.crm.base import (
    HTTP_TIMEOUT,
    PUSH_CONCURRENCY,
    CRMContact,
    CRMConnector,
    CrmOAuthTokens,
    PushResult,
    _http_retry,
    sanitize_error,
)

logger = structlog.get_logger()

_AUTH_URL = "https://login.salesforce.com/services/oauth2/authorize"
_TOKEN_URL = "https://login.salesforce.com/services/oauth2/token"
_API_VERSION = "v59.0"


def _contact_fields(contact: CRMContact) -> dict:
    last = contact.last_name or contact.email.split("@", 1)[0]
    fields = {"LastName": last, "Email": contact.email}
    if contact.first_name:
        fields["FirstName"] = contact.first_name
    if contact.phone:
        fields["Phone"] = contact.phone
    if contact.job_title:
        fields["Title"] = contact.job_title
    if contact.city:
        fields["MailingCity"] = contact.city
    if contact.region:
        fields["MailingState"] = contact.region
    if contact.country:
        fields["MailingCountry"] = contact.country
    return fields


class SalesforceConnector(CRMConnector):
    provider = "salesforce"
    auth_type = "oauth"

    async def get_auth_url(self, state: str) -> str:
        params = {
            "response_type": "code",
            "client_id": settings.salesforce_client_id,
            "redirect_uri": settings.salesforce_redirect_uri,
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
        # Salesforce access tokens don't carry expires_in; they're refreshed
        # reactively on a 401. We leave expires_at None.
        return CrmOAuthTokens(
            access_token=payload.get("access_token", ""),
            refresh_token=payload.get("refresh_token"),
            expires_at=None,
            external_account_id=payload.get("instance_url", ""),
            external_account_label="Salesforce",
        )

    async def exchange_code(self, code: str, state: str = "") -> CrmOAuthTokens:
        if settings.mock_external_apis:
            return CrmOAuthTokens(
                access_token="mock_salesforce_token",
                refresh_token="mock_salesforce_refresh",
                expires_at=None,
                external_account_id="https://mock.my.salesforce.com",
                external_account_label="Salesforce (mock)",
            )
        payload = await self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": settings.salesforce_client_id,
                "client_secret": settings.salesforce_client_secret,
                "redirect_uri": settings.salesforce_redirect_uri,
            }
        )
        return self._tokens_from_payload(payload)

    async def refresh_tokens(self, refresh_token: str) -> CrmOAuthTokens:
        if settings.mock_external_apis:
            return CrmOAuthTokens(
                access_token="mock_salesforce_token",
                refresh_token=refresh_token,
                expires_at=None,
                external_account_id="https://mock.my.salesforce.com",
                external_account_label="Salesforce (mock)",
            )
        payload = await self._token_request(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": settings.salesforce_client_id,
                "client_secret": settings.salesforce_client_secret,
            }
        )
        tokens = self._tokens_from_payload(payload)
        # Refresh responses omit the refresh token — keep the existing one.
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
        if not access_token or not instance_url:
            return False
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                resp = await client.get(
                    f"{instance_url}/services/data/{_API_VERSION}/limits",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            return resp.status_code == 200
        except httpx.HTTPError as exc:
            logger.warning("crm_salesforce_test_failed", error=sanitize_error(exc))
            return False

    @_http_retry
    async def _find_contact_id(
        self, client: httpx.AsyncClient, instance_url: str, access_token: str, email: str
    ) -> str | None:
        safe = email.replace("'", "\\'")
        resp = await client.get(
            f"{instance_url}/services/data/{_API_VERSION}/query",
            params={"q": f"SELECT Id FROM Contact WHERE Email = '{safe}' LIMIT 1"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        records = resp.json().get("records") or []
        return records[0]["Id"] if records else None

    @_http_retry
    async def _create_or_update(
        self,
        client: httpx.AsyncClient,
        instance_url: str,
        access_token: str,
        contact_id: str | None,
        fields: dict,
    ) -> None:
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        base = f"{instance_url}/services/data/{_API_VERSION}/sobjects/Contact"
        if contact_id:
            resp = await client.patch(f"{base}/{contact_id}", json=fields, headers=headers)
        else:
            resp = await client.post(base, json=fields, headers=headers)
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
        if not access_token or not instance_url:
            return PushResult(pushed=0, failed=len(contacts), errors=["Salesforce not connected"])

        sem = asyncio.Semaphore(PUSH_CONCURRENCY)
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:

            async def _one(contact: CRMContact) -> tuple[bool, str | None]:
                async with sem:
                    try:
                        cid = await self._find_contact_id(
                            client, instance_url, access_token, contact.email
                        )
                        await self._create_or_update(
                            client, instance_url, access_token, cid, _contact_fields(contact)
                        )
                        return True, None
                    except httpx.HTTPError as exc:
                        msg = sanitize_error(exc)
                        logger.warning("crm_salesforce_push_failed", error=msg)
                        return False, msg

            results = await asyncio.gather(*[_one(c) for c in contacts])

        pushed = sum(1 for ok, _ in results if ok)
        failed = len(results) - pushed
        errors: list[str] = []
        for ok, msg in results:
            if not ok and msg and msg not in errors:
                errors.append(msg)
        return PushResult(pushed=pushed, failed=failed, errors=errors)
