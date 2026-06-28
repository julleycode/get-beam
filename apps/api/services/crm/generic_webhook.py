"""Generic webhook connector — POSTs contacts to any URL with an HMAC signature.

Connects Beam to anything that can receive a webhook (Zapier, Make, a custom
endpoint). No OAuth. The receiver verifies authenticity via the
`X-Beam-Signature` header: hex HMAC-SHA256 of the raw body using the shared
secret (same idiom as services/shopify_integration.verify_hmac).
"""

import hashlib
import hmac
import json
from dataclasses import asdict

import httpx
import structlog

from apps.api.config import settings
from apps.api.services.crm.base import (
    HTTP_TIMEOUT,
    CRMContact,
    CRMConnector,
    PushResult,
    _http_retry,
    sanitize_error,
)
from apps.api.services.url_guard import is_safe_public_url

logger = structlog.get_logger()


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class GenericWebhookConnector(CRMConnector):
    provider = "generic_webhook"
    auth_type = "webhook"

    @_http_retry
    async def _post(self, webhook_url: str, secret: str, payload: dict) -> int:
        body = json.dumps(payload).encode()
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(
                webhook_url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Beam-Signature": _sign(secret, body),
                },
            )
        resp.raise_for_status()
        return resp.status_code

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
        if not webhook_url or not await is_safe_public_url(webhook_url):
            return False
        try:
            await self._post(webhook_url, secret, {"type": "ping", "source": "beam"})
            return True
        except httpx.HTTPError as exc:
            logger.warning("crm_webhook_test_failed", error=sanitize_error(exc))
            return False

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
        if not webhook_url:
            return PushResult(pushed=0, failed=len(contacts), errors=["Webhook URL not configured"])
        if not await is_safe_public_url(webhook_url):
            return PushResult(
                pushed=0, failed=len(contacts), errors=["Webhook URL is not a public address"]
            )
        payload = {"type": "contacts", "contacts": [asdict(c) for c in contacts]}
        try:
            await self._post(webhook_url, secret, payload)
            return PushResult(pushed=len(contacts), failed=0, errors=[])
        except httpx.HTTPError as exc:
            msg = sanitize_error(exc)
            logger.warning("crm_webhook_push_failed", count=len(contacts), error=msg)
            return PushResult(pushed=0, failed=len(contacts), errors=[msg])
