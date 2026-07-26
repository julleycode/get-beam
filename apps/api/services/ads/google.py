"""Google Customer Match provider — real two-API wiring (Phase 3).

Every method keeps the Phase-1 ``settings.mock_external_apis`` short-circuit
first, so dev/tests/demo stay keyless and deterministic. Below that branch is
the real path.

TWO APIs, deliberately (A1/A1b docs-fetch, 26-07-2026):

  1. **Google Ads API** (``googleads.googleapis.com``, scope ``.../adwords``,
     ``developer-token`` header) CREATES the Customer Match ``UserList``.
     The Data Manager API has no equivalent create call in the flow this
     phase implements, so the list must exist before members can be ingested.
     ``platform_audience_id`` therefore ALWAYS comes from this call's
     ``results[].resourceName`` — never from the Data Manager response.
  2. **Data Manager API** (``datamanager.googleapis.com``, scope
     ``.../datamanager``) POPULATES it via ``audienceMembers:ingest``, which
     returns ONLY an async ``requestId`` — no per-member success counts, and
     never an audience id.

Token model: unlike Meta (which re-exchanges the CURRENT access token via
``fb_exchange_token``), Google issues a distinct, long-lived refresh secret.
See ``refresh_tokens``.

Only SHA256 digests are uploaded: ``ads_push.build_hashed_contacts`` hashes
upstream and this module never sees or re-hashes a plaintext identifier.

Never log the access token, the refresh token, the developer token, the OAuth
``code``, or any contact value.
"""

import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import structlog
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from apps.api.config import settings
from apps.api.services.ads.base import (
    HTTP_TIMEOUT,
    AdOAuthTokens,
    AdsProvider,
    AdTestOutcome,
    AudienceResult,
    HashedContact,
    sanitize_error,
)
from apps.api.services.encryption import decrypt_token

logger = structlog.get_logger()

# Live-probed 26-07-2026 against googleads.googleapis.com: v20-v25 answer 401
# (exist), v17-v19 and v26+ answer 404 (sunset / not yet released). v25 is the
# current version and the one the public reference documents. Google sunsets a
# version roughly yearly — RECHECK and bump this single constant; it is never
# inlined at a call site.
GOOGLE_ADS_API_VERSION = "v25"

_GOOGLE_ADS_BASE = f"https://googleads.googleapis.com/{GOOGLE_ADS_API_VERSION}"
# Data Manager API is unversioned-in-host; v1 is the only released version
# (discovery doc `datamanager:v1`, revision 20260722).
_DATA_MANAGER_BASE = "https://datamanager.googleapis.com/v1"

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"

# `datamanager` ingests audience members; `adwords` creates the UserList they
# are ingested into. Both are required — one without the other is a half-flow.
_SCOPES = [
    "https://www.googleapis.com/auth/datamanager",
    "https://www.googleapis.com/auth/adwords",
]

# csv_exporter._sha256 emits a lowercase hex digest, so the ingest call must
# declare HEX (the alternative the API accepts is BASE64).
_HASH_ENCODING = "HEX"

# Data Manager caps a single ingest request at 10000 AudienceMember resources.
_INGEST_BATCH_SIZE = 10000

_TRANSIENT_HTTP_STATUSES = {429, 500, 502, 503, 504}


def _is_transient_http_error(exc: BaseException) -> bool:
    """Retry timeouts, connection errors, and 5xx/429 — never a 4xx we caused."""
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _TRANSIENT_HTTP_STATUSES
    return False


# 3 attempts, exponential backoff 1→2→8s, transient errors only. Mirrors
# services/ads/meta.py's _http_retry; replicated locally because
# services/ads/base.py is frozen for this phase.
_http_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception(_is_transient_http_error),
    reraise=True,
)


def _customer_id(connection) -> str:
    """Bare, hyphen-free Google Ads customer id for the connection.

    Google Ads shows `123-456-7890` in the UI but every API path segment and
    header wants `1234567890`.
    """
    raw = (getattr(connection, "ad_account_id", "") or "").strip()
    cid = raw.replace("-", "")
    if not cid:
        raise RuntimeError(
            "This Google connection has no Google Ads customer id — reconnect it."
        )
    return cid


def _access_token(connection) -> str:
    token = getattr(connection, "access_token", "") or ""
    if not token:
        raise RuntimeError("This Google connection has no stored access token.")
    return decrypt_token(token)


def _user_list_id(resource_name: str) -> str:
    """`customers/123/userLists/456` -> `456`.

    Data Manager's `productDestinationId` wants the bare list id, not the
    Google Ads resource name.
    """
    return (resource_name or "").rsplit("/", 1)[-1]


class GoogleAdsProvider(AdsProvider):
    provider = "google"

    # ── HTTP helpers ─────────────────────────────────────

    @_http_retry
    async def _ads_post(self, url: str, payload: dict, token: str) -> dict:
        """POST to the Google Ads API.

        `developer-token` is required on every call. `login-customer-id` is
        deliberately NOT sent: it is only required when a MANAGER account
        calls on behalf of a client account, and Beam's connection model is
        direct-customer (docs-confirmed A1b, 26-07-2026).
        """
        headers = {
            "Authorization": f"Bearer {token}",
            "developer-token": settings.google_ads_developer_token,
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()

    @_http_retry
    async def _ads_get(self, url: str, token: str) -> dict:
        headers = {
            "Authorization": f"Bearer {token}",
            "developer-token": settings.google_ads_developer_token,
        }
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()

    @_http_retry
    async def _dm_post(self, url: str, payload: dict, token: str) -> dict:
        """POST to the Data Manager API (no developer-token header here)."""
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(
                url, json=payload, headers={"Authorization": f"Bearer {token}"}
            )
        resp.raise_for_status()
        return resp.json()

    @_http_retry
    async def _oauth_post(self, data: dict) -> dict:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(_TOKEN_URL, data=data)
        resp.raise_for_status()
        return resp.json()

    # ── Step B: OAuth ────────────────────────────────────

    async def get_oauth_url(self, state: str) -> str:
        if settings.mock_external_apis:
            return f"https://mock.google.test/o/oauth2/auth?state={state}"
        params = {
            "client_id": settings.google_ads_client_id,
            "redirect_uri": settings.google_ads_redirect_uri,
            "state": state,
            "scope": " ".join(_SCOPES),
            "response_type": "code",
            # Google issues a refresh_token ONLY on a first/re-granted consent
            # with access_type=offline. Both params are mandatory here: without
            # them the exchange returns an access token that silently cannot be
            # refreshed, and the connection dies at first expiry.
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, state: str = "") -> AdOAuthTokens:
        if settings.mock_external_apis:
            return AdOAuthTokens(
                access_token=f"mock-google-token-{uuid.uuid4().hex}",
                refresh_token=f"mock-google-refresh-{uuid.uuid4().hex}",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                scopes=list(_SCOPES),
                external_account_id="mock-google-account",
                external_account_label="Google Customer Match (mock)",
                ad_account_id="123-456-7890",
            )

        payload = await self._oauth_post(
            {
                "code": code,
                "client_id": settings.google_ads_client_id,
                "client_secret": settings.google_ads_client_secret,
                "redirect_uri": settings.google_ads_redirect_uri,
                "grant_type": "authorization_code",
            }
        )
        access_token = payload.get("access_token", "")
        if not access_token:
            raise RuntimeError("Google did not return an access token")

        tokens = AdOAuthTokens(
            access_token=access_token,
            refresh_token=payload.get("refresh_token") or None,
            expires_at=_expiry_from(payload),
            scopes=list(_SCOPES),
            external_account_label="Google Customer Match",
        )

        # Best-effort customer discovery — a connection without a customer id
        # can still be repaired by reconnecting, so never fail the exchange.
        try:
            accessible = await self._ads_get(
                f"{_GOOGLE_ADS_BASE}/customers:listAccessibleCustomers", access_token
            )
            first = (accessible.get("resourceNames") or [""])[0]
            customer_id = first.rsplit("/", 1)[-1] if first else ""
            tokens.ad_account_id = customer_id
            tokens.external_account_id = customer_id
        except Exception as exc:  # noqa: BLE001 — degraded, not fatal
            logger.warning(
                "google_accessible_customers_lookup_failed", error=sanitize_error(exc)
            )

        return tokens

    async def refresh_tokens(self, refresh_token: str) -> AdOAuthTokens:
        """Mint a new access token from the STORED refresh secret.

        STRUCTURALLY DIFFERENT FROM META. ``MetaAdsProvider.refresh_tokens``
        takes the CURRENT, not-yet-expired ACCESS token and re-exchanges it
        (``fb_exchange_token``), because Meta issues no separate refresh
        secret. Google does the opposite: it issues a distinct, long-lived
        ``refresh_token`` at first consent, and THAT secret — never the access
        token — is the input here. The refresh call does not replace the
        refresh secret itself; the same one is reused until revoked.

        Consequence for callers: ``ads_push.fresh_access_token`` must pass the
        decrypted ``conn.refresh_token`` for Google, and the decrypted
        ``conn.access_token`` for Meta. Do not assume the Meta shape applies.

        Lifetime note (A2/SPEC OQ3): under a **Testing**-status OAuth consent
        screen the refresh token expires after 7 days and the consent flow must
        be re-run; under a **Published** screen it is indefinite, subject to
        revocation and a 6-month-unused expiry.

        Declared only on this class, not on the shared ``AdsProvider`` ABC —
        ``services/ads/base.py`` is frozen. Callers ``getattr``-guard it; see
        ``ads_push.fresh_access_token``.
        """
        if settings.mock_external_apis:
            return AdOAuthTokens(
                access_token=f"mock-google-token-{uuid.uuid4().hex}",
                refresh_token=None,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                scopes=list(_SCOPES),
                external_account_label="Google Customer Match (mock)",
            )
        if not refresh_token:
            raise RuntimeError("This Google connection has no stored refresh token.")

        payload = await self._oauth_post(
            {
                "grant_type": "refresh_token",
                "client_id": settings.google_ads_client_id,
                "client_secret": settings.google_ads_client_secret,
                "refresh_token": refresh_token,
            }
        )
        access_token = payload.get("access_token", "")
        if not access_token:
            raise RuntimeError("Google did not return a refreshed access token")
        return AdOAuthTokens(
            access_token=access_token,
            # Google reuses the same refresh secret; it is not re-issued here.
            refresh_token=None,
            expires_at=_expiry_from(payload),
            scopes=list(_SCOPES),
            external_account_label="Google Customer Match",
        )

    # ── Test ─────────────────────────────────────────────

    async def test_connection(self, connection) -> AdTestOutcome:
        if settings.mock_external_apis:
            return AdTestOutcome(is_valid=True, message="Connection is live (mock)")
        try:
            await self._ads_get(
                f"{_GOOGLE_ADS_BASE}/customers:listAccessibleCustomers",
                _access_token(connection),
            )
        except Exception as exc:  # noqa: BLE001 — surface a sanitized reason
            return AdTestOutcome(
                is_valid=False, message=sanitize_error(exc, "Connection test failed")
            )
        return AdTestOutcome(is_valid=True, message="Connection is live")

    # ── Step C: audience create + member ingest ──────────

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

        token = _access_token(connection)
        customer_id = _customer_id(connection)

        # C1: first push creates the UserList via the GOOGLE ADS API; a repeat
        # push reuses the stored id instead of creating a duplicate (AC6).
        audience_id = getattr(link, "platform_audience_id", "") if link else ""
        if not audience_id:
            audience_id = await self._create_user_list(customer_id, connection, token)

        if not hashed_contacts:
            return AudienceResult(platform_audience_id=audience_id, pushed=0)

        # C2: populate via the DATA MANAGER API. Its response carries only an
        # async requestId — it is NEVER a source of the audience id.
        pushed = await self._ingest_members(
            customer_id, audience_id, hashed_contacts, token
        )
        return AudienceResult(platform_audience_id=audience_id, pushed=pushed)

    async def _create_user_list(self, customer_id: str, connection, token: str) -> str:
        """Create a Customer Match UserList and return its resource name."""
        site_id = getattr(connection, "site_id", "")
        created = await self._ads_post(
            f"{_GOOGLE_ADS_BASE}/customers/{customer_id}/userLists:mutate",
            {
                "operations": [
                    {
                        "create": {
                            "name": f"Beam segment {site_id} {uuid.uuid4().hex[:8]}".strip(),
                            "description": "Created by Beam from a visitor segment.",
                            "membershipLifeSpan": 10000,  # 10000 = no expiry
                            "crmBasedUserList": {
                                # Hashed emails only, first-party data.
                                "uploadKeyType": "CONTACT_INFO",
                                "dataSourceType": "FIRST_PARTY",
                            },
                        }
                    }
                ]
            },
            token,
        )
        resource_name = ((created.get("results") or [{}])[0]).get("resourceName", "")
        if not resource_name:
            raise RuntimeError("Google did not return a user list resource name")
        return resource_name

    async def _ingest_members(
        self,
        customer_id: str,
        audience_id: str,
        hashed_contacts: list[HashedContact],
        token: str,
    ) -> int:
        """Ingest hashed members into an existing UserList. Returns count sent.

        The ingest is asynchronous: the response is a bare ``requestId``, so
        "pushed" here means "accepted for processing", never a
        platform-confirmed match count. Same fire-and-forget stance as Meta.
        """
        destination = {
            "operatingAccount": {
                "accountId": customer_id,
                "accountType": "GOOGLE_ADS",
            },
            "productDestinationId": _user_list_id(audience_id),
        }
        sent = 0
        for start in range(0, len(hashed_contacts), _INGEST_BATCH_SIZE):
            batch = hashed_contacts[start : start + _INGEST_BATCH_SIZE]
            result = await self._dm_post(
                f"{_DATA_MANAGER_BASE}/audienceMembers:ingest",
                {
                    "destinations": [destination],
                    "audienceMembers": [
                        {
                            "userData": {
                                "userIdentifiers": [
                                    {"emailAddress": c.email_sha256}
                                ]
                            }
                        }
                        for c in batch
                    ],
                    "encoding": _HASH_ENCODING,
                    # Request-level consent. Beam excludes EEA rows entirely
                    # upstream (ads_push, SPEC OQ4 decision c), so every row
                    # reaching here is non-EEA and consent is GRANTED.
                    "consent": {
                        "adUserData": "CONSENT_GRANTED",
                        "adPersonalization": "CONSENT_GRANTED",
                    },
                    # Required on any ingest carrying UserData.
                    "termsOfService": {
                        "customerMatchTermsOfServiceStatus": "ACCEPTED"
                    },
                },
                token,
            )
            sent += len(batch)
            logger.info(
                "google_audience_ingest_ack",
                audience_id=audience_id,
                request_id=result.get("requestId", ""),
                members=len(batch),
            )
        return sent


def _expiry_from(payload: dict) -> datetime | None:
    expires_in = int(payload.get("expires_in") or 0)
    if not expires_in:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=expires_in)
