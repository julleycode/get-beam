"""Phase 2 — MetaAdsProvider unit coverage (mock mode + mocked httpx only).

No live Meta call is made anywhere in this file. The real-mode paths are
exercised by monkeypatching MetaAdsProvider._get / _post, so the request
shaping, the two-step token exchange, the create-vs-reuse branch, the
EMAIL_SHA256 payload, and the AC13 ToS error mapping are all provable offline.

Also covers the A3c safe-guard: ads_push.fresh_access_token must NOT raise
AttributeError for a provider that has no refresh_tokens method (Google /
LinkedIn today), because services/ads/base.py declares no ABC-level default.
"""

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from apps.api.config import settings
from apps.api.services.ads import meta as meta_mod
from apps.api.services.ads.base import HashedContact
from apps.api.services.ads.meta import (
    GRAPH_API_VERSION,
    SCHEMA_EMAIL_SHA256,
    MetaAdsProvider,
    MetaAudienceTermsError,
)

pytestmark = pytest.mark.unit


class _Conn:
    """Minimal AdConnection stand-in — no DB needed."""

    def __init__(self, ad_account_id="act_123", access_token="enc-token"):
        self.ad_account_id = ad_account_id
        self.access_token = access_token
        self.refresh_token = None
        self.token_expires_at = None
        self.site_id = "site_x"
        self.provider = "meta"
        self.status = "connected"
        self.is_valid = True
        self.last_error = None


class _Link:
    def __init__(self, platform_audience_id):
        self.platform_audience_id = platform_audience_id


@pytest.fixture
def real_mode(monkeypatch):
    """Turn OFF mock mode so the real code path runs — with mocked transport."""
    monkeypatch.setattr(settings, "mock_external_apis", False)
    monkeypatch.setattr(settings, "meta_ads_client_id", "cid")
    monkeypatch.setattr(settings, "meta_ads_client_secret", "csecret")
    monkeypatch.setattr(
        settings, "meta_ads_redirect_uri", "https://beam.test/api/v1/ads/callback/meta"
    )
    # Real token decryption is out of scope here — identity keeps assertions honest.
    monkeypatch.setattr(meta_mod, "decrypt_token", lambda t: f"plain-{t}")


@pytest.fixture
def mock_mode(monkeypatch):
    monkeypatch.setattr(settings, "mock_external_apis", True)


# ── A1: version pinning ──────────────────────────────────

def test_graph_version_is_a_single_named_constant():
    assert GRAPH_API_VERSION == "v25.0"
    # Every URL must be built from the constant, never an inline literal.
    assert GRAPH_API_VERSION in meta_mod._GRAPH_BASE
    assert GRAPH_API_VERSION in meta_mod._OAUTH_DIALOG_URL
    assert GRAPH_API_VERSION in meta_mod._TOKEN_URL


# ── A2: OAuth URL shape ──────────────────────────────────

async def test_oauth_url_mock_mode_short_circuits(mock_mode):
    url = await MetaAdsProvider().get_oauth_url("st8")
    assert url == "https://mock.meta.test/dialog/oauth?state=st8"


async def test_oauth_url_real_mode_shape(real_mode):
    url = await MetaAdsProvider().get_oauth_url("st8")
    assert url.startswith(f"https://www.facebook.com/{GRAPH_API_VERSION}/dialog/oauth?")
    assert "client_id=cid" in url
    assert "state=st8" in url
    assert "response_type=code" in url
    # Meta wants a comma-separated scope string, not spaces.
    assert "scope=ads_management%2Cbusiness_management" in url
    assert "redirect_uri=https%3A%2F%2Fbeam.test" in url


# ── A3: two-step token exchange ──────────────────────────

async def test_exchange_code_is_a_two_step_exchange_storing_long_lived_expiry(
    real_mode, monkeypatch
):
    calls = []

    async def fake_get(self, url, params):
        calls.append(params)
        if params.get("grant_type") == "fb_exchange_token":
            return {"access_token": "LONG", "expires_in": 5184000}  # ~60d
        if "adaccounts" in url:
            return {
                "data": [
                    {"id": "act_999", "account_id": "999", "name": "Acme",
                     "business": {"id": "biz1"}}
                ]
            }
        return {"access_token": "SHORT", "expires_in": 3600}  # 1h

    monkeypatch.setattr(MetaAdsProvider, "_get", fake_get)
    tokens = await MetaAdsProvider().exchange_code("auth-code")

    # Step 1 used the code; step 2 exchanged the SHORT token for the long one.
    assert calls[0]["code"] == "auth-code"
    assert calls[1]["grant_type"] == "fb_exchange_token"
    assert calls[1]["fb_exchange_token"] == "SHORT"

    # The stored token + expiry are the LONG-lived ones, never the 1h value.
    assert tokens.access_token == "LONG"
    assert tokens.refresh_token is None  # Meta issues no separate refresh secret
    delta = tokens.expires_at - datetime.now(timezone.utc)
    assert delta > timedelta(days=50), "stored the short-lived expiry by mistake"

    assert tokens.ad_account_id == "act_999"
    assert tokens.business_id == "biz1"
    assert tokens.external_account_label == "Acme"


async def test_exchange_code_survives_adaccounts_lookup_failure(real_mode, monkeypatch):
    async def fake_get(self, url, params):
        if "adaccounts" in url:
            raise httpx.ConnectError("boom")
        if params.get("grant_type") == "fb_exchange_token":
            return {"access_token": "LONG", "expires_in": 5184000}
        return {"access_token": "SHORT"}

    monkeypatch.setattr(MetaAdsProvider, "_get", fake_get)
    tokens = await MetaAdsProvider().exchange_code("c")
    # Degraded, not fatal — the connection is still usable/repairable.
    assert tokens.access_token == "LONG"
    assert tokens.external_account_label


async def test_exchange_code_mock_mode_is_deterministic_and_long_lived(mock_mode):
    tokens = await MetaAdsProvider().exchange_code("ignored")
    assert tokens.access_token.startswith("mock-meta-token-")
    assert tokens.ad_account_id == "act_mock"
    assert tokens.expires_at > datetime.now(timezone.utc) + timedelta(days=50)


# ── A3b: refresh_tokens ──────────────────────────────────

async def test_refresh_tokens_reruns_only_the_fb_exchange_step(real_mode, monkeypatch):
    seen = {}

    async def fake_get(self, url, params):
        seen.update(params)
        return {"access_token": "LONG2", "expires_in": 5184000}

    monkeypatch.setattr(MetaAdsProvider, "_get", fake_get)
    tokens = await MetaAdsProvider().refresh_tokens("current-long-token")

    assert seen["grant_type"] == "fb_exchange_token"
    # The INPUT is the current access token — not a separate refresh secret.
    assert seen["fb_exchange_token"] == "current-long-token"
    assert "code" not in seen
    assert tokens.access_token == "LONG2"


def test_refresh_tokens_docstring_warns_it_takes_an_access_token():
    doc = (MetaAdsProvider.refresh_tokens.__doc__ or "").lower()
    assert "not a refresh secret" in doc or "not_a_refresh_secret" in doc


def test_refresh_tokens_is_not_on_the_shared_abc():
    """base.py is frozen this phase — the guard in ads_push depends on this."""
    from apps.api.services.ads.base import AdsProvider

    assert not hasattr(AdsProvider, "refresh_tokens")


# ── B1/B2: audience create + upload ──────────────────────

def _contacts(n):
    return [HashedContact(email_sha256=f"{i:064x}") for i in range(n)]


async def test_first_push_creates_audience_then_uploads(real_mode, monkeypatch):
    posts = []

    async def fake_post(self, url, data, account_hint=""):
        posts.append((url, data))
        if url.endswith("/customaudiences"):
            return {"id": "aud-777"}
        return {"num_received": 3, "num_invalid_entries": 0}

    monkeypatch.setattr(MetaAdsProvider, "_post", fake_post)
    result = await MetaAdsProvider().create_or_update_audience(
        _Conn(), None, _contacts(3)
    )

    create_url, create_body = posts[0]
    assert create_url.endswith(f"/{GRAPH_API_VERSION}/act_123/customaudiences")
    assert create_body["subtype"] == "CUSTOM"
    assert create_body["customer_file_source"] == "USER_PROVIDED_ONLY"

    upload_url, upload_body = posts[1]
    assert upload_url.endswith("/aud-777/users")
    assert result.platform_audience_id == "aud-777"
    assert result.pushed == 3


async def test_repeat_push_reuses_the_link_audience_id_and_skips_creation(
    real_mode, monkeypatch
):
    posts = []

    async def fake_post(self, url, data, account_hint=""):
        posts.append(url)
        return {"num_received": 2, "num_invalid_entries": 0}

    monkeypatch.setattr(MetaAdsProvider, "_post", fake_post)
    result = await MetaAdsProvider().create_or_update_audience(
        _Conn(), _Link("existing-aud"), _contacts(2)
    )

    assert result.platform_audience_id == "existing-aud"
    assert len(posts) == 1, "a repeat push must NOT create a second audience"
    assert posts[0].endswith("/existing-aud/users")


async def test_upload_uses_the_docs_confirmed_email_sha256_schema_key(
    real_mode, monkeypatch
):
    """B1b: single-key uploads use EMAIL_SHA256, not the multi-key 'EMAIL'."""
    import json

    captured = {}

    async def fake_post(self, url, data, account_hint=""):
        if url.endswith("/users"):
            captured.update(json.loads(data["payload"]))
        return {"id": "a1", "num_received": 1, "num_invalid_entries": 0}

    monkeypatch.setattr(MetaAdsProvider, "_post", fake_post)
    contacts = _contacts(1)
    await MetaAdsProvider().create_or_update_audience(_Conn(), _Link("a1"), contacts)

    assert SCHEMA_EMAIL_SHA256 == "EMAIL_SHA256"
    assert captured["schema"] == "EMAIL_SHA256"
    assert captured["is_raw"] is True
    # Only digests leave — never a plaintext identifier.
    assert captured["data"] == [contacts[0].email_sha256]


async def test_invalid_entries_are_reported_as_failed(real_mode, monkeypatch):
    async def fake_post(self, url, data, account_hint=""):
        return {"num_received": 5, "num_invalid_entries": 2}

    monkeypatch.setattr(MetaAdsProvider, "_post", fake_post)
    result = await MetaAdsProvider().create_or_update_audience(
        _Conn(), _Link("a1"), _contacts(5)
    )
    assert result.pushed == 3
    assert result.failed == 2


async def test_empty_contact_list_skips_the_upload_call(real_mode, monkeypatch):
    posts = []

    async def fake_post(self, url, data, account_hint=""):
        posts.append(url)
        return {"id": "new-aud"}

    monkeypatch.setattr(MetaAdsProvider, "_post", fake_post)
    result = await MetaAdsProvider().create_or_update_audience(_Conn(), None, [])
    assert result.pushed == 0
    assert not any(u.endswith("/users") for u in posts)


async def test_missing_ad_account_id_fails_with_an_actionable_message(real_mode):
    with pytest.raises(RuntimeError, match="ad account id"):
        await MetaAdsProvider().create_or_update_audience(
            _Conn(ad_account_id=""), None, _contacts(1)
        )


# ── Step C / AC13: ToS-precondition error ────────────────

def _resp(status, payload):
    return httpx.Response(
        status_code=status, json=payload, request=httpx.Request("POST", "https://x.test")
    )


def test_tos_detector_matches_the_documented_400_message():
    assert meta_mod._is_tos_error(
        _resp(400, {"error": {"message": "Custom Audience Terms not yet accepted"}})
    )


def test_tos_detector_ignores_unrelated_400s_and_non_400s():
    assert not meta_mod._is_tos_error(_resp(400, {"error": {"message": "Invalid param"}}))
    assert not meta_mod._is_tos_error(
        _resp(500, {"error": {"message": "Custom Audience Terms not yet accepted"}})
    )


def test_tos_message_is_specific_and_carries_the_remediation_url():
    msg = meta_mod._tos_error_message("act_555")
    assert "Custom Audience Terms" in msg
    assert "business.facebook.com/ads/manage/customaudiences/tos/?act=555" in msg


async def test_tos_error_raises_the_dedicated_exception_not_a_generic_failure(
    real_mode, monkeypatch
):
    async def fake_post_transport(self, url, data, account_hint=""):
        # Re-run the real detector against a documented ToS 400 body.
        resp = _resp(400, {"error": {"message": "Custom Audience Terms not yet accepted"}})
        if meta_mod._is_tos_error(resp):
            raise MetaAudienceTermsError(meta_mod._tos_error_message(account_hint))
        resp.raise_for_status()

    monkeypatch.setattr(MetaAdsProvider, "_post", fake_post_transport)
    with pytest.raises(MetaAudienceTermsError) as exc:
        await MetaAdsProvider().create_or_update_audience(_Conn(), None, _contacts(1))
    assert "tos/?act=123" in str(exc.value)


# ── E2 retry policy ──────────────────────────────────────

def test_only_transient_errors_are_retried():
    assert meta_mod._is_transient_http_error(httpx.TimeoutException("t"))
    assert meta_mod._is_transient_http_error(httpx.ConnectError("c"))
    assert meta_mod._is_transient_http_error(
        httpx.HTTPStatusError("x", request=None, response=_resp(503, {}))
    )
    # A 400 is our fault — retrying it just burns quota.
    assert not meta_mod._is_transient_http_error(
        httpx.HTTPStatusError("x", request=None, response=_resp(400, {}))
    )


# ── A3c guard: fresh_access_token must not crash non-Meta providers ──

class _FakeDB:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


class _NoRefreshProvider:
    """Stands in for GoogleAdsProvider / LinkedInAdsProvider today."""


async def test_fresh_access_token_skips_providers_without_refresh_tokens(monkeypatch):
    from apps.api.services import ads_push

    monkeypatch.setattr(ads_push, "decrypt_token", lambda t: "plain")
    monkeypatch.setattr(ads_push, "get_provider", lambda name: _NoRefreshProvider())

    conn = _Conn()
    conn.provider = "google"
    conn.token_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)  # expired

    # Must NOT raise AttributeError — base.py has no refresh_tokens default.
    token = await ads_push.fresh_access_token(_FakeDB(), conn)
    assert token == "plain"
    assert conn.status == "connected", "a skipped refresh must not error the connection"


async def test_fresh_access_token_is_a_noop_while_the_token_is_still_valid(monkeypatch):
    from apps.api.services import ads_push

    called = False

    class _Spy:
        async def refresh_tokens(self, current):
            nonlocal called
            called = True

    monkeypatch.setattr(ads_push, "decrypt_token", lambda t: "plain")
    monkeypatch.setattr(ads_push, "get_provider", lambda name: _Spy())

    conn = _Conn()
    conn.token_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    assert await ads_push.fresh_access_token(_FakeDB(), conn) == "plain"
    assert called is False


async def test_fresh_access_token_refreshes_and_reencrypts_when_expired(monkeypatch):
    from apps.api.services import ads_push
    from apps.api.services.ads.base import AdOAuthTokens

    new_expiry = datetime.now(timezone.utc) + timedelta(days=60)

    class _Refresher:
        async def refresh_tokens(self, current):
            assert current == "plain"  # current access token, not a refresh secret
            return AdOAuthTokens(access_token="NEW", expires_at=new_expiry)

    monkeypatch.setattr(ads_push, "decrypt_token", lambda t: "plain")
    monkeypatch.setattr(ads_push, "encrypt_token", lambda t: f"enc({t})")
    monkeypatch.setattr(ads_push, "get_provider", lambda name: _Refresher())

    conn = _Conn()
    conn.token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    token = await ads_push.fresh_access_token(_FakeDB(), conn)

    assert token == "NEW"
    assert conn.access_token == "enc(NEW)"
    assert conn.token_expires_at == new_expiry


async def test_fresh_access_token_marks_the_connection_on_refresh_failure(monkeypatch):
    from apps.api.services import ads_push

    class _Broken:
        async def refresh_tokens(self, current):
            raise httpx.ConnectError("down")

    monkeypatch.setattr(ads_push, "decrypt_token", lambda t: "plain")
    monkeypatch.setattr(ads_push, "get_provider", lambda name: _Broken())

    conn = _Conn()
    conn.token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    token = await ads_push.fresh_access_token(_FakeDB(), conn)

    assert token == "plain"  # falls back to the stale token rather than crashing
    assert conn.status == "error"
    assert conn.is_valid is False
    assert conn.last_error
    assert "plain" not in conn.last_error  # never leaks a token into last_error
