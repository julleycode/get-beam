"""Meta Custom Audiences provider — real Graph API wiring (Phase 2).

Every method keeps the Phase-1 ``settings.mock_external_apis`` short-circuit
first, so dev/tests/demo stay keyless and deterministic. Below that branch is
the real Marketing API path.

Token model (Phase 2, INNOVATE-decided): Meta has no separate refresh-token
secret. ``exchange_code`` performs a TWO-STEP exchange — auth code -> short-lived
token (1-2h) -> long-lived token (~60d) — and stores the LONG-lived expiry.
``refresh_tokens`` re-runs only the second step, using the current still-valid
access token as its input.

Only SHA256 digests are uploaded: ``ads_push.build_hashed_contacts`` hashes
upstream and this module never sees or re-hashes a plaintext identifier.

Never log the access token, the OAuth ``code``, or any contact value.
"""

import json
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

# Meta deprecates a Graph API version roughly 2 years after release. v25.0 is
# the Feb-2026 release, re-confirmed against the primary Custom Audience users
# reference page on 26-07-2026 (its live example request carries
# `&version=v25.0`). RECHECK BEFORE ~2028-02 and bump this one constant — it is
# deliberately the single source of truth, never inlined at a call site.
GRAPH_API_VERSION = "v25.0"

_GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
_OAUTH_DIALOG_URL = f"https://www.facebook.com/{GRAPH_API_VERSION}/dialog/oauth"
_TOKEN_URL = f"{_GRAPH_BASE}/oauth/access_token"

_SCOPES = ["ads_management", "business_management"]

# Single-key hashed-email upload. Docs-confirmed (B1b, 26-07-2026) against
# https://developers.facebook.com/docs/marketing-api/reference/custom-audience/users/ :
# "schema string EMAIL_SHA256, PHONE_SHA256, MOBILE_ADVERTISER_ID". The short
# "EMAIL" spelling is only valid inside the MULTI-key array form
# (["EMAIL","LN","FN","ZIP"]), which Beam does not use.
SCHEMA_EMAIL_SHA256 = "EMAIL_SHA256"

# AC13: an ad account that has not signed the Custom Audience Terms of Service
# cannot create or edit a custom-file audience. Meta returns HTTP 400; the
# documented remediation link is per-ad-account.
_TOS_URL_TEMPLATE = "https://business.facebook.com/ads/manage/customaudiences/tos/?act={account_id}"
# Substrings that identify the ToS-precondition failure in a Graph error body.
# TODO Agent-Probe: confirm the real error `code`/`subcode` against a live
# sandbox — Meta's docs do not publish them, so this stays message-text matching
# (SPEC keeps AC13 at Agent-Probe tier for exactly this reason).
_TOS_ERROR_MARKERS = (
    "custom audience terms",
    "terms of service",
    "customaudience_tos",
)

_TRANSIENT_HTTP_STATUSES = {429, 500, 502, 503, 504}


def _is_transient_http_error(exc: BaseException) -> bool:
    """Retry timeouts, connection errors, and 5xx/429 — never a 4xx we caused."""
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _TRANSIENT_HTTP_STATUSES
    return False


# 3 attempts, exponential backoff 1→2→8s, transient errors only. Mirrors
# services/crm/base.py's _http_retry; replicated locally because
# services/ads/base.py is frozen for this phase.
_http_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception(_is_transient_http_error),
    reraise=True,
)


class MetaAudienceTermsError(RuntimeError):
    """The ad account has not accepted Meta's Custom Audience Terms (AC13).

    Carries an actionable message including the per-account remediation URL, so
    the user gets a next step instead of a bare "push failed".
    """


def _tos_error_message(account_id: str) -> str:
    acct = (account_id or "").replace("act_", "") or "YOUR_AD_ACCOUNT"
    return (
        "Meta rejected this push because this ad account hasn't accepted the "
        "Custom Audience Terms of Service yet. Accept them here, then try "
        f"again: {_TOS_URL_TEMPLATE.format(account_id=acct)}"
    )


def _is_tos_error(resp: httpx.Response) -> bool:
    """True when a Graph 400 looks like the unaccepted-ToS precondition."""
    if resp.status_code != 400:
        return False
    try:
        body = resp.json()
    except ValueError:
        body = {}
    error = body.get("error") or {}
    haystack = " ".join(
        str(error.get(k, "")) for k in ("message", "error_user_msg", "error_user_title")
    ).lower()
    if not haystack.strip():
        haystack = resp.text[:2000].lower()
    return any(marker in haystack for marker in _TOS_ERROR_MARKERS)


def _account_path(connection) -> str:
    """`act_<id>` path segment for the connection's ad account."""
    account_id = (getattr(connection, "ad_account_id", "") or "").strip()
    if not account_id:
        raise RuntimeError("This Meta connection has no ad account id — reconnect it.")
    return account_id if account_id.startswith("act_") else f"act_{account_id}"


def _access_token(connection) -> str:
    token = getattr(connection, "access_token", "") or ""
    if not token:
        raise RuntimeError("This Meta connection has no stored access token.")
    return decrypt_token(token)


class MetaAdsProvider(AdsProvider):
    provider = "meta"

    # ── HTTP helpers ─────────────────────────────────────

    @_http_retry
    async def _get(self, url: str, params: dict) -> dict:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    @_http_retry
    async def _post(self, url: str, data: dict, account_hint: str = "") -> dict:
        """POST to the Graph API. ``account_hint`` is used only to build the
        AC13 remediation URL on a ToS failure — it is never sent to Meta."""
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(url, data=data)
        if _is_tos_error(resp):
            raise MetaAudienceTermsError(_tos_error_message(account_hint))
        resp.raise_for_status()
        return resp.json()

    # ── Step A: OAuth ────────────────────────────────────

    async def get_oauth_url(self, state: str) -> str:
        if settings.mock_external_apis:
            return f"https://mock.meta.test/dialog/oauth?state={state}"
        params = {
            "client_id": settings.meta_ads_client_id,
            "redirect_uri": settings.meta_ads_redirect_uri,
            "state": state,
            "scope": ",".join(_SCOPES),
            "response_type": "code",
        }
        return f"{_OAUTH_DIALOG_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, state: str = "") -> AdOAuthTokens:
        if settings.mock_external_apis:
            return AdOAuthTokens(
                access_token=f"mock-meta-token-{uuid.uuid4().hex}",
                refresh_token=None,
                expires_at=datetime.now(timezone.utc) + timedelta(days=60),
                scopes=list(_SCOPES),
                external_account_id="mock-meta-account",
                external_account_label="Meta Custom Audiences (mock)",
                ad_account_id="act_mock",
                business_id="mock-business",
            )

        # Step 1 — auth code → SHORT-lived token (1-2h). Its expiry is discarded
        # on purpose: only the long-lived expiry is ever persisted.
        short = await self._get(
            _TOKEN_URL,
            {
                "client_id": settings.meta_ads_client_id,
                "client_secret": settings.meta_ads_client_secret,
                "redirect_uri": settings.meta_ads_redirect_uri,
                "code": code,
            },
        )
        short_token = short.get("access_token", "")
        if not short_token:
            raise RuntimeError("Meta did not return an access token")

        # Step 2 — short-lived → LONG-lived token (~60d). This is the one we store.
        tokens = await self._long_lived_tokens(short_token)

        # Best-effort account discovery — a connection without an ad account can
        # still be repaired by reconnecting, so never fail the whole exchange.
        try:
            accounts = await self._get(
                f"{_GRAPH_BASE}/me/adaccounts",
                {
                    "access_token": tokens.access_token,
                    "fields": "id,account_id,name,business",
                    "limit": 1,
                },
            )
            first = (accounts.get("data") or [{}])[0]
            tokens.ad_account_id = first.get("id") or (
                f"act_{first['account_id']}" if first.get("account_id") else ""
            )
            tokens.external_account_id = tokens.ad_account_id
            tokens.external_account_label = first.get("name") or "Meta Custom Audiences"
            tokens.business_id = (first.get("business") or {}).get("id", "")
        except Exception as exc:  # noqa: BLE001 — degraded, not fatal
            logger.warning("meta_adaccounts_lookup_failed", error=sanitize_error(exc))
            tokens.external_account_label = tokens.external_account_label or "Meta Custom Audiences"

        return tokens

    async def _long_lived_tokens(self, current_access_token: str) -> AdOAuthTokens:
        """Run Meta's `fb_exchange_token` grant and shape the result."""
        payload = await self._get(
            _TOKEN_URL,
            {
                "grant_type": "fb_exchange_token",
                "client_id": settings.meta_ads_client_id,
                "client_secret": settings.meta_ads_client_secret,
                "fb_exchange_token": current_access_token,
            },
        )
        access_token = payload.get("access_token", "")
        if not access_token:
            raise RuntimeError("Meta did not return a long-lived access token")
        expires_in = int(payload.get("expires_in") or 0)
        return AdOAuthTokens(
            access_token=access_token,
            refresh_token=None,  # Meta issues no separate refresh secret
            expires_at=(
                datetime.now(timezone.utc) + timedelta(seconds=expires_in)
                if expires_in
                else None
            ),
            scopes=list(_SCOPES),
            external_account_label="Meta Custom Audiences",
        )

    async def refresh_tokens(self, current_access_token: str) -> AdOAuthTokens:
        """Extend a long-lived Meta token.

        ``current_access_token`` is the CURRENT, NOT-YET-EXPIRED access token —
        NOT a refresh secret. Meta has no separate refresh token: the long-lived
        access token is itself the input to the ``fb_exchange_token`` grant, so
        this must be called before the stored token actually expires. (This is
        why it differs from the CRM connectors, which pass a distinct
        ``refresh_token``.)

        Declared only on this class, not on the shared ``AdsProvider`` ABC —
        ``services/ads/base.py`` is frozen for Phase 2. Callers must therefore
        ``getattr``-guard the lookup; see ``ads_push.fresh_access_token``.
        """
        if settings.mock_external_apis:
            return AdOAuthTokens(
                access_token=f"mock-meta-token-{uuid.uuid4().hex}",
                refresh_token=None,
                expires_at=datetime.now(timezone.utc) + timedelta(days=60),
                scopes=list(_SCOPES),
                external_account_label="Meta Custom Audiences (mock)",
            )
        return await self._long_lived_tokens(current_access_token)

    # ── Test ─────────────────────────────────────────────

    async def test_connection(self, connection) -> AdTestOutcome:
        if settings.mock_external_apis:
            return AdTestOutcome(is_valid=True, message="Connection is live (mock)")
        try:
            await self._get(
                f"{_GRAPH_BASE}/me/adaccounts",
                {"access_token": _access_token(connection), "limit": 1},
            )
        except Exception as exc:  # noqa: BLE001 — surface a sanitized reason
            return AdTestOutcome(is_valid=False, message=sanitize_error(exc, "Connection test failed"))
        return AdTestOutcome(is_valid=True, message="Connection is live")

    # ── Step B: Custom Audience create + upload ──────────

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

        token = _access_token(connection)
        account_path = _account_path(connection)

        # B1: first push (no link row yet) creates the audience; a repeat push
        # reuses the stored id instead of creating a duplicate (AC6).
        audience_id = getattr(link, "platform_audience_id", "") if link else ""
        if not audience_id:
            created = await self._post(
                f"{_GRAPH_BASE}/{account_path}/customaudiences",
                {
                    "access_token": token,
                    "name": f"Beam segment {getattr(connection, 'site_id', '')}".strip(),
                    "description": "Created by Beam from a visitor segment.",
                    "subtype": "CUSTOM",
                    "customer_file_source": "USER_PROVIDED_ONLY",
                },
                account_hint=account_path,
            )
            audience_id = created.get("id", "")
            if not audience_id:
                raise RuntimeError("Meta did not return a custom audience id")

        if not hashed_contacts:
            return AudienceResult(platform_audience_id=audience_id, pushed=0)

        # B2: single-key hashed-email upload. `is_raw` stays true because each
        # value is already one SHA256 digest, not a combinational key.
        payload = {
            "schema": SCHEMA_EMAIL_SHA256,
            "is_raw": True,
            "data": [c.email_sha256 for c in hashed_contacts],
        }
        # B3 (fire-and-forget, v1): Meta processes the upload asynchronously but
        # acknowledges synchronously. That ack is the terminal result for this
        # push — no polling task. `num_received` is Beam-side "queued/matched",
        # never a platform-confirmed audience size.
        result = await self._post(
            f"{_GRAPH_BASE}/{audience_id}/users",
            {
                "access_token": token,
                "payload": json.dumps(payload),
            },
            account_hint=account_path,
        )
        received = int(result.get("num_received") or 0)
        invalid = int(result.get("num_invalid_entries") or 0)
        pushed = max(0, (received or len(hashed_contacts)) - invalid)

        logger.info(
            "meta_audience_upload_ack",
            audience_id=audience_id,
            received=received,
            invalid=invalid,
        )
        return AudienceResult(
            platform_audience_id=audience_id,
            pushed=pushed,
            failed=invalid,
        )
