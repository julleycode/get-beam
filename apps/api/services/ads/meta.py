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
    AdPerformanceRow,
    AdTestOutcome,
    AudienceResult,
    ConversionEvent,
    ConversionResult,
    HashedContact,
    LookalikeResult,
    LookalikeSpec,
    coerce_float,
    coerce_int,
    sanitize_error,
)
from apps.api.services.click_ids import meta_fbc
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

    # ── closed-won-lookalikes: lookalike from a processed seed ──

    async def create_lookalike(
        self, connection, seed_audience_id: str, spec: LookalikeSpec
    ) -> LookalikeResult:
        return await _meta_create_lookalike(self, connection, seed_audience_id, spec)

    # ── conversion-apis: Conversions API (server-side events) ──

    async def send_conversions(
        self, connection, config, events: list[ConversionEvent]
    ) -> list[ConversionResult]:
        """POST hashed website events to ``/{dataset_id}/events``.

        Stale (>6d) and no-UA rows are filtered by the sweep BEFORE this call
        (Meta rejects a whole batch for one >7d event). One outbox attempt is
        exactly ONE HTTP call — this path deliberately does not use the
        ``@_http_retry`` helper so outbox backoff never stacks on tenacity (E6).
        """
        if not events:
            return []
        if settings.mock_external_apis:
            return [ConversionResult(delivery_id=e.delivery_id, ok=True) for e in events]

        dataset_id = (getattr(config, "meta_dataset_id", "") or "").strip()
        if not dataset_id:
            return [
                ConversionResult(delivery_id=e.delivery_id, ok=False, error="no_dataset")
                for e in events
            ]
        token = _access_token(connection)
        results: list[ConversionResult] = []
        for start in range(0, len(events), META_CAPI_BATCH_SIZE):
            batch = events[start : start + META_CAPI_BATCH_SIZE]
            data = build_meta_capi_request(config, batch)
            data["access_token"] = token
            try:
                async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                    resp = await client.post(f"{_GRAPH_BASE}/{dataset_id}/events", data=data)
                resp.raise_for_status()
            except Exception as exc:  # noqa: BLE001 — classified, sanitized
                transient = _is_transient_http_error(exc)
                reason = sanitize_error(exc)
                results.extend(
                    ConversionResult(
                        delivery_id=e.delivery_id, ok=False, error=reason, transient=transient
                    )
                    for e in batch
                )
                continue
            results.extend(ConversionResult(delivery_id=e.delivery_id, ok=True) for e in batch)
            logger.info("meta_capi_ack", events=len(batch))
        return results

    # ── ad-insights-seo-aeo: read-only reporting ──

    async def fetch_ad_performance(self, connection, since, until) -> list[AdPerformanceRow]:
        """Per-ad daily insights + creative text. Read-only Graph calls only."""
        if settings.mock_external_apis:
            return parse_meta_insights(*mock_meta_report())
        token = _access_token(connection)
        account_path = _account_path(connection)
        params: dict | None = {
            "access_token": token,
            "level": "ad",
            "time_increment": 1,
            "time_range": json.dumps(
                {"since": since.isoformat(), "until": until.isoformat()}
            ),
            "fields": "ad_id,ad_name,adset_name,campaign_name,impressions,clicks,ctr,actions,date_start",
            "limit": 500,
        }
        url: str | None = f"{_GRAPH_BASE}/{account_path}/insights"
        pages: list[dict] = []
        for _ in range(_META_MAX_PAGES):
            if not url:
                break
            # paging.next already carries every query param (incl. the token).
            page = await self._get(url, params or {})
            pages.append(page)
            url = ((page.get("paging") or {}).get("next")) or None
            params = None
        ad_ids = sorted(
            {str(r.get("ad_id")) for p in pages for r in (p.get("data") or []) if r.get("ad_id")}
        )
        creatives: dict = {}
        for start in range(0, len(ad_ids), _META_IDS_BATCH):
            chunk = ad_ids[start : start + _META_IDS_BATCH]
            creatives.update(
                await self._get(
                    f"{_GRAPH_BASE}/",
                    {
                        "access_token": token,
                        "ids": ",".join(chunk),
                        "fields": "creative{title,body,object_story_spec,asset_feed_spec,link_url}",
                    },
                )
                or {}
            )
        return parse_meta_insights(pages, creatives)


# Meta CAPI accepts up to 1000 events per request.
META_CAPI_BATCH_SIZE = 1000


def build_meta_capi_event(event: ConversionEvent) -> dict:
    """One Meta CAPI ``website`` event. Hashed identifiers only; no raw IP (D4)."""
    user_data: dict = {"client_user_agent": event.user_agent}
    if event.email_sha256:
        user_data["em"] = [event.email_sha256]
    if event.phone_sha256:
        user_data["ph"] = [event.phone_sha256]
    fbc = meta_fbc(event.click_ids)
    if fbc:
        user_data["fbc"] = fbc
    when = event.event_time
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return {
        "event_name": event.event_name,
        "event_time": int(when.timestamp()),
        "event_id": event.dedup_id,
        "action_source": "website",
        "event_source_url": event.event_source_url,
        "user_data": user_data,
    }


def build_meta_capi_request(config, events: list[ConversionEvent]) -> dict:
    """Form body for ``POST /{dataset_id}/events`` (access_token added by caller)."""
    body: dict = {"data": json.dumps([build_meta_capi_event(e) for e in events])}
    test_code = (getattr(config, "meta_test_event_code", "") or "").strip()
    if test_code:
        body["test_event_code"] = test_code
    return body


# ── closed-won-lookalikes: lookalike audience ───────────

# Meta drops ``lookalike_spec.country`` after v26 (location moves to ad-set
# targeting). Beam pins v25, so country is sent; the guard keeps a future
# version bump from silently sending a field Meta rejects.
_LOOKALIKE_COUNTRY_MAX_VERSION = 26


def graph_major_version(version: str = GRAPH_API_VERSION) -> int:
    try:
        return int(version.lstrip("v").split(".", 1)[0])
    except ValueError:
        return 0


def build_meta_lookalike_payload(
    seed_audience_id: str, spec: LookalikeSpec, version: str = GRAPH_API_VERSION
) -> dict:
    """Form body for ``POST act_{id}/customaudiences`` (access_token added by caller)."""
    lookalike_spec: dict = {"ratio": spec.ratio, "type": "similarity"}
    if graph_major_version(version) <= _LOOKALIKE_COUNTRY_MAX_VERSION:
        lookalike_spec["country"] = spec.country
    return {
        "name": f"Beam closed-won lookalike {spec.country} {spec.ratio}",
        "subtype": "LOOKALIKE",
        "origin_audience_id": seed_audience_id,
        "lookalike_spec": json.dumps(lookalike_spec),
    }


def meta_seed_warning(seed_size: int) -> str:
    if seed_size < settings.meta_lookalike_min_seed:
        return (
            f"Your seed has {seed_size} people. Meta needs at least "
            f"{settings.meta_lookalike_min_seed} matched people for a lookalike — "
            "it may fail or stay empty until the seed grows."
        )
    return ""


def _graph_error_message(resp: httpx.Response) -> str:
    """Meta's own error text (seed not ready, too small). Contains no contact data."""
    try:
        err = (resp.json() or {}).get("error") or {}
    except ValueError:
        err = {}
    msg = str(err.get("error_user_msg") or err.get("message") or "").strip()
    return (msg or f"Provider returned HTTP {resp.status_code}")[:300]


async def _meta_create_lookalike(
    provider, connection, seed_audience_id: str, spec: LookalikeSpec
) -> LookalikeResult:
    if settings.mock_external_apis:
        return LookalikeResult(audience_id=f"mock-meta-lal-{uuid.uuid4().hex[:12]}")
    token = _access_token(connection)
    account_path = _account_path(connection)
    data = {"access_token": token, **build_meta_lookalike_payload(seed_audience_id, spec)}
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(f"{_GRAPH_BASE}/{account_path}/customaudiences", data=data)
    except httpx.HTTPError as exc:
        return LookalikeResult(status="error", error=sanitize_error(exc, "Lookalike create failed"))
    if _is_tos_error(resp):
        return LookalikeResult(status="error", error=_tos_error_message(account_path))
    if resp.status_code >= 400:
        return LookalikeResult(status="error", error=_graph_error_message(resp))
    audience_id = str((resp.json() or {}).get("id") or "")
    if not audience_id:
        return LookalikeResult(status="error", error="Meta did not return a lookalike audience id")
    logger.info("meta_lookalike_created")
    return LookalikeResult(audience_id=audience_id)


# ── ad-insights-seo-aeo: report parsing (pure, docs-derived — KG-1) ──

_META_MAX_PAGES = 50
_META_IDS_BATCH = 50


def _first_text(items) -> str:
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict) and isinstance(it.get("text"), str) and it["text"].strip():
                return it["text"]
    return ""


def meta_creative_text(node: dict) -> tuple[str, str, str]:
    """(headline, body, landing_url) from an ad's ``creative`` node.

    Dynamic creatives keep their copy in ``asset_feed_spec`` (G-5); link ads in
    ``object_story_spec.link_data``. Unknown shapes yield empty strings.
    """
    creative = (node or {}).get("creative") if isinstance(node, dict) else None
    if not isinstance(creative, dict):
        return "", "", ""
    headline = creative.get("title") or ""
    body = creative.get("body") or ""
    link = creative.get("link_url") or ""
    story = creative.get("object_story_spec") or {}
    link_data = story.get("link_data") if isinstance(story, dict) else None
    if isinstance(link_data, dict):
        headline = headline or link_data.get("name") or ""
        body = body or link_data.get("message") or ""
        link = link or link_data.get("link") or ""
    feed = creative.get("asset_feed_spec") or {}
    if isinstance(feed, dict):
        headline = headline or _first_text(feed.get("titles"))
        body = body or _first_text(feed.get("bodies"))
        if not link:
            for lu in feed.get("link_urls") or []:
                if isinstance(lu, dict) and lu.get("website_url"):
                    link = lu["website_url"]
                    break
    return str(headline), str(body), str(link)


def meta_conversions(actions) -> float:
    """Value of the first configured action_type present (ordered, no summing)."""
    if not isinstance(actions, list):
        return 0.0
    by_type = {}
    for a in actions:
        if isinstance(a, dict) and a.get("action_type") and a["action_type"] not in by_type:
            by_type[a["action_type"]] = a.get("value")
    for wanted in settings.ad_insights_meta_conversion_action_types:
        if wanted in by_type:
            return coerce_float(by_type[wanted])
    return 0.0


def parse_meta_insights(pages, creatives: dict) -> list[AdPerformanceRow]:
    """Insights pages (``{"data": [...]}``) + ``?ids=`` creative map -> rows."""
    from datetime import date as _date

    if isinstance(pages, dict):
        pages = [pages]
    rows: list[AdPerformanceRow] = []
    for page in pages or []:
        for r in (page or {}).get("data") or []:
            if not isinstance(r, dict) or not r.get("ad_id"):
                continue
            try:
                day = _date.fromisoformat(str(r.get("date_start"))[:10])
            except ValueError:
                continue
            ad_id = str(r["ad_id"])
            headline, body, link = meta_creative_text((creatives or {}).get(ad_id) or {})
            rows.append(
                AdPerformanceRow(
                    platform_ad_id=ad_id,
                    date=day,
                    impressions=coerce_int(r.get("impressions")),
                    clicks=coerce_int(r.get("clicks")),
                    conversions=meta_conversions(r.get("actions")),
                    campaign_name=str(r.get("campaign_name") or ""),
                    headline=headline or str(r.get("ad_name") or ""),
                    body=body,
                    landing_url=link,
                )
            )
    return rows


def mock_meta_report() -> tuple[list[dict], dict]:
    """Deterministic mock report; dates are relative to today (UTC) so the rows
    always fall inside the lookback window."""
    from datetime import timedelta as _td

    base = datetime.now(timezone.utc).date() - _td(days=3)
    specs = [
        ("m-101", "Find who visits your site", "/pricing", 4000, 160, "8"),
        ("m-102", "Turn anonymous visitors into leads", "/features", 3000, 60, "3"),
        ("m-103", "Retargeting without the bots", "/blog/retargeting", 2500, 75, "1"),
        ("m-104", "Tiny test ad", "/", 100, 20, "2"),
    ]
    data = []
    creatives: dict = {}
    for ad_id, title, path, imp, clk, conv in specs:
        for d in range(2):
            data.append({
                "ad_id": ad_id, "ad_name": title, "campaign_name": "Mock campaign",
                "impressions": str(imp // 2), "clicks": str(clk // 2),
                "actions": [{"action_type": "lead", "value": conv}],
                "date_start": (base + _td(days=d)).isoformat(),
            })
        creatives[ad_id] = {"creative": {"title": title, "body": f"{title} with Beam.",
                                         "link_url": f"https://example.com{path}"}}
    return [{"data": data}], creatives

