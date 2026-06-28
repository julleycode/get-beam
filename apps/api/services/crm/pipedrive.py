"""Pipedrive connector — OAuth + Persons upsert (search-by-email then create/update).

Pipedrive issues a company-specific `api_domain` on token exchange (e.g.
https://yourco.pipedrive.com). We persist it in the connection's
`external_account_id` and the router passes it back as `instance_url`.

Pipedrive has no native email-idempotent upsert, so we search Persons by email
(exact) and PUT the match or POST a new one.
"""

import asyncio
from datetime import datetime, timedelta, timezone
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

_AUTH_URL = "https://oauth.pipedrive.com/oauth/authorize"
_TOKEN_URL = "https://oauth.pipedrive.com/oauth/token"


def _person_body(contact: CRMContact) -> dict:
    name = f"{contact.first_name} {contact.last_name}".strip() or contact.email
    body: dict = {"name": name, "email": [{"value": contact.email, "primary": True}]}
    if contact.phone:
        body["phone"] = [{"value": contact.phone, "primary": True}]
    if contact.job_title:
        body["job_title"] = contact.job_title
    return body


class PipedriveConnector(CRMConnector):
    provider = "pipedrive"
    auth_type = "oauth"

    async def get_auth_url(self, state: str) -> str:
        params = {
            "client_id": settings.pipedrive_client_id,
            "redirect_uri": settings.pipedrive_redirect_uri,
            "state": state,
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    @_http_retry
    async def _token_request(self, data: dict) -> dict:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(
                _TOKEN_URL,
                data=data,
                auth=(settings.pipedrive_client_id, settings.pipedrive_client_secret),
            )
        resp.raise_for_status()
        return resp.json()

    def _tokens_from_payload(self, payload: dict) -> CrmOAuthTokens:
        expires_in = int(payload.get("expires_in", 0) or 0)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in) if expires_in else None
        )
        api_domain = payload.get("api_domain", "")
        return CrmOAuthTokens(
            access_token=payload.get("access_token", ""),
            refresh_token=payload.get("refresh_token"),
            expires_at=expires_at,
            external_account_id=api_domain,
            external_account_label="Pipedrive",
        )

    async def exchange_code(self, code: str, state: str = "") -> CrmOAuthTokens:
        if settings.mock_external_apis:
            return CrmOAuthTokens(
                access_token="mock_pipedrive_token",
                refresh_token="mock_pipedrive_refresh",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                external_account_id="https://mock.pipedrive.com",
                external_account_label="Pipedrive (mock)",
            )
        payload = await self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.pipedrive_redirect_uri,
            }
        )
        return self._tokens_from_payload(payload)

    async def refresh_tokens(self, refresh_token: str) -> CrmOAuthTokens:
        if settings.mock_external_apis:
            return CrmOAuthTokens(
                access_token="mock_pipedrive_token",
                refresh_token=refresh_token,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                external_account_id="https://mock.pipedrive.com",
                external_account_label="Pipedrive (mock)",
            )
        payload = await self._token_request(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )
        tokens = self._tokens_from_payload(payload)
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
                    f"{instance_url}/api/v1/users/me",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            return resp.status_code == 200
        except httpx.HTTPError as exc:
            logger.warning("crm_pipedrive_test_failed", error=sanitize_error(exc))
            return False

    @_http_retry
    async def _search_person_id(
        self, client: httpx.AsyncClient, instance_url: str, access_token: str, email: str
    ) -> int | None:
        resp = await client.get(
            f"{instance_url}/api/v1/persons/search",
            params={"term": email, "fields": "email", "exact_match": "true", "limit": 1},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        items = (resp.json().get("data") or {}).get("items") or []
        return items[0]["item"]["id"] if items else None

    @_http_retry
    async def _create_or_update(
        self,
        client: httpx.AsyncClient,
        instance_url: str,
        access_token: str,
        person_id: int | None,
        body: dict,
    ) -> None:
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        if person_id:
            resp = await client.put(
                f"{instance_url}/api/v1/persons/{person_id}", json=body, headers=headers
            )
        else:
            resp = await client.post(
                f"{instance_url}/api/v1/persons", json=body, headers=headers
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
        if not access_token or not instance_url:
            return PushResult(pushed=0, failed=len(contacts), errors=["Pipedrive not connected"])

        sem = asyncio.Semaphore(PUSH_CONCURRENCY)
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:

            async def _one(contact: CRMContact) -> tuple[bool, str | None]:
                async with sem:
                    try:
                        pid = await self._search_person_id(
                            client, instance_url, access_token, contact.email
                        )
                        await self._create_or_update(
                            client, instance_url, access_token, pid, _person_body(contact)
                        )
                        return True, None
                    except httpx.HTTPError as exc:
                        msg = sanitize_error(exc)
                        logger.warning("crm_pipedrive_push_failed", error=msg)
                        return False, msg

            results = await asyncio.gather(*[_one(c) for c in contacts])

        pushed = sum(1 for ok, _ in results if ok)
        failed = len(results) - pushed
        errors: list[str] = []
        for ok, msg in results:
            if not ok and msg and msg not in errors:
                errors.append(msg)
        return PushResult(pushed=pushed, failed=failed, errors=errors)
