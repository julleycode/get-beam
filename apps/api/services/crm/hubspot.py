"""HubSpot connector — OAuth + Contacts batch upsert (idempotent on email)."""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import structlog

from apps.api.config import settings
from apps.api.services.crm.base import (
    HTTP_TIMEOUT,
    ClosedWonDeal,
    ClosedWonFetch,
    CRMContact,
    CRMConnector,
    CrmOAuthTokens,
    PushResult,
    _http_retry,
    mock_closed_won_deals,
    sanitize_error,
)

logger = structlog.get_logger()

_AUTH_URL = "https://app.hubspot.com/oauth/authorize"
_TOKEN_URL = "https://api.hubapi.com/oauth/v1/token"
_CONTACTS_URL = "https://api.hubapi.com/crm/v3/objects/contacts"
_BATCH_UPSERT_URL = "https://api.hubapi.com/crm/v3/objects/contacts/batch/upsert"
_SCOPES = "crm.objects.contacts.write crm.objects.contacts.read crm.objects.deals.read"
DEALS_SCOPE = "crm.objects.deals.read"
_BATCH_SIZE = 100  # HubSpot batch limit
_PIPELINES_URL = "https://api.hubapi.com/crm/v3/pipelines/deals"
_DEALS_SEARCH_URL = "https://api.hubapi.com/crm/v3/objects/deals/search"
_DEAL_CONTACTS_URL = "https://api.hubapi.com/crm/v4/objects/deals/{deal_id}/associations/contacts"
_CONTACTS_BATCH_READ_URL = "https://api.hubapi.com/crm/v3/objects/contacts/batch/read"
# HubSpot search returns at most 10,000 results per query; re-window before it.
SEARCH_RESULT_CAP = 10_000
_SEARCH_PAGE = 100
_MAX_WINDOWS = 50  # hard stop against a runaway re-window loop


def has_deals_scope(scopes: list[str] | None) -> bool:
    return DEALS_SCOPE in (scopes or [])


def won_stage_ids(pipelines_payload: dict) -> list[str]:
    """Won stages = ``metadata.isClosed == "true"`` AND probability 1.0.

    Never the literal ``closedwon`` — custom pipelines use their own stage ids.
    """
    ids: list[str] = []
    for pipeline in pipelines_payload.get("results") or []:
        for stage in pipeline.get("stages") or []:
            meta = stage.get("metadata") or {}
            try:
                probability = float(meta.get("probability", ""))
            except (TypeError, ValueError):
                continue
            if str(meta.get("isClosed", "")).lower() == "true" and probability == 1.0:
                if stage.get("id"):
                    ids.append(str(stage["id"]))
    return ids


def deals_search_body(stage_ids: list[str], since: datetime | None, after: str | None) -> dict:
    filters: list[dict] = [{"propertyName": "dealstage", "operator": "IN", "values": stage_ids}]
    if since is not None:
        filters.append(
            {
                "propertyName": "hs_lastmodifieddate",
                "operator": "GTE",
                "value": str(int(since.timestamp() * 1000)),
            }
        )
    body: dict = {
        "filterGroups": [{"filters": filters}],
        "sorts": [{"propertyName": "hs_lastmodifieddate", "direction": "ASCENDING"}],
        "properties": ["closedate", "hs_lastmodifieddate", "dealstage"],
        "limit": _SEARCH_PAGE,
    }
    if after:
        body["after"] = after
    return body


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
        except (TypeError, ValueError):
            return None

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

    # ── closed-won-lookalikes: read-back ─────────────────

    @_http_retry
    async def _get_json(self, url: str, access_token: str) -> dict:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {access_token}"})
        resp.raise_for_status()
        return resp.json()

    @_http_retry
    async def _post_json(self, url: str, access_token: str, body: dict) -> dict:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(
                url, json=body, headers={"Authorization": f"Bearer {access_token}"}
            )
        resp.raise_for_status()
        return resp.json()

    async def _deal_emails(self, access_token: str, deal_id: str) -> list[str]:
        assoc = await self._get_json(_DEAL_CONTACTS_URL.format(deal_id=deal_id), access_token)
        contact_ids = [
            str(r.get("toObjectId")) for r in assoc.get("results") or [] if r.get("toObjectId")
        ]
        if not contact_ids:
            return []
        read = await self._post_json(
            _CONTACTS_BATCH_READ_URL,
            access_token,
            {"properties": ["email"], "inputs": [{"id": cid} for cid in contact_ids[:_BATCH_SIZE]]},
        )
        emails = []
        for r in read.get("results") or []:
            email = ((r.get("properties") or {}).get("email") or "").strip()
            if email:
                emails.append(email)
        return emails

    async def fetch_closed_won(
        self,
        *,
        access_token: str = "",
        instance_url: str = "",
        scopes: list[str] | None = None,
        since: datetime | None = None,
    ) -> ClosedWonFetch:
        if settings.mock_external_apis:
            return ClosedWonFetch(deals=mock_closed_won_deals("hubspot"))
        # Old tokens were granted before deals.read existed: never fetch, prompt reconnect.
        if not has_deals_scope(scopes):
            return ClosedWonFetch(needs_reconnect=True)
        if not access_token:
            return ClosedWonFetch()

        stage_ids = won_stage_ids(await self._get_json(_PIPELINES_URL, access_token))
        if not stage_ids:
            return ClosedWonFetch()

        deals: list[ClosedWonDeal] = []
        cursor = since
        window_since = since
        for _ in range(_MAX_WINDOWS):
            after: str | None = None
            seen_in_window = 0
            window_max: datetime | None = None
            while True:
                page = await self._post_json(
                    _DEALS_SEARCH_URL,
                    access_token,
                    deals_search_body(stage_ids, window_since, after),
                )
                results = page.get("results") or []
                for deal in results:
                    props = deal.get("properties") or {}
                    modified = _parse_ts(props.get("hs_lastmodifieddate"))
                    if modified and (window_max is None or modified > window_max):
                        window_max = modified
                    for email in await self._deal_emails(access_token, str(deal.get("id"))):
                        deals.append(
                            ClosedWonDeal(
                                external_deal_id=str(deal.get("id")),
                                email=email,
                                closed_at=_parse_ts(props.get("closedate")),
                            )
                        )
                seen_in_window += len(results)
                after = ((page.get("paging") or {}).get("next") or {}).get("after")
                if not after or seen_in_window + _SEARCH_PAGE > SEARCH_RESULT_CAP:
                    break
            if window_max and (cursor is None or window_max > cursor):
                cursor = window_max
            # More results remain past the 10k cap: restart from the last seen
            # modified time (sorted ASC). Upsert is idempotent on overlap.
            if after and window_max is not None and window_max != window_since:
                window_since = window_max
                continue
            break

        logger.info("crm_hubspot_closed_won_fetched", deals=len(deals))
        return ClosedWonFetch(deals=deals, cursor=cursor)
