"""Phase 3 — GoogleAdsProvider unit coverage (mock mode + mocked httpx only).

No live Google call is made anywhere in this file. Real-mode paths are
exercised by monkeypatching the provider's transport helpers, so the OAuth URL
params, the refresh-secret grant, the two-API create+ingest sequence, and the
consent/ToS payload fields are all provable offline.

Also covers E1b: ads_push.fresh_access_token must pass the decrypted REFRESH
token for Google and keep passing the decrypted ACCESS token for Meta.
"""

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from apps.api.config import settings
from apps.api.services.ads import google as google_mod
from apps.api.services.ads.base import HashedContact
from apps.api.services.ads.google import (
    GOOGLE_ADS_API_VERSION,
    GoogleAdsProvider,
)

pytestmark = pytest.mark.unit


class _Conn:
    """Minimal AdConnection stand-in — no DB needed."""

    def __init__(self, ad_account_id="123-456-7890", access_token="enc-token"):
        self.ad_account_id = ad_account_id
        self.access_token = access_token
        self.refresh_token = None
        self.token_expires_at = None
        self.site_id = "site_x"
        self.provider = "google"
        self.status = "connected"
        self.is_valid = True
        self.last_error = None


class _Link:
    def __init__(self, platform_audience_id):
        self.platform_audience_id = platform_audience_id


@pytest.fixture
def real_mode(monkeypatch):
    monkeypatch.setattr(settings, "mock_external_apis", False)
    monkeypatch.setattr(settings, "google_ads_client_id", "cid")
    monkeypatch.setattr(settings, "google_ads_client_secret", "csecret")
    monkeypatch.setattr(settings, "google_ads_developer_token", "devtok")
    monkeypatch.setattr(
        settings,
        "google_ads_redirect_uri",
        "https://beam.test/api/v1/ads/callback/google",
    )
    monkeypatch.setattr(google_mod, "decrypt_token", lambda t: f"plain-{t}")


@pytest.fixture
def mock_mode(monkeypatch):
    monkeypatch.setattr(settings, "mock_external_apis", True)


def _contacts(n):
    return [HashedContact(email_sha256=f"{i:064x}") for i in range(n)]


# ── A1b: version pinning ─────────────────────────────────

def test_api_version_is_a_single_named_constant():
    assert GOOGLE_ADS_API_VERSION == "v25"
    assert GOOGLE_ADS_API_VERSION in google_mod._GOOGLE_ADS_BASE


# ── B1/B5: OAuth URL shape ───────────────────────────────

async def test_oauth_url_mock_mode_short_circuits(mock_mode):
    url = await GoogleAdsProvider().get_oauth_url("st8")
    assert url == "https://mock.google.test/o/oauth2/auth?state=st8"


async def test_oauth_url_carries_offline_access_and_forced_consent(real_mode):
    """Without BOTH params Google never issues a refresh_token (B5)."""
    url = await GoogleAdsProvider().get_oauth_url("st8")
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "client_id=cid" in url
    assert "state=st8" in url
    assert "response_type=code" in url


async def test_oauth_url_pairs_the_datamanager_and_adwords_scopes(real_mode):
    url = await GoogleAdsProvider().get_oauth_url("st8")
    assert "auth%2Fdatamanager" in url
    assert "auth%2Fadwords" in url
    # Google wants space-separated scopes (encoded as +), not commas.
    assert "%2C" not in url.split("scope=")[1].split("&")[0]


# ── B2: token exchange ───────────────────────────────────

async def test_exchange_code_stores_both_tokens_and_discovers_the_customer_id(
    real_mode, monkeypatch
):
    seen = {}

    async def fake_oauth_post(self, data):
        seen.update(data)
        return {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600}

    async def fake_ads_get(self, url, token):
        assert "listAccessibleCustomers" in url
        return {"resourceNames": ["customers/9998887776"]}

    monkeypatch.setattr(GoogleAdsProvider, "_oauth_post", fake_oauth_post)
    monkeypatch.setattr(GoogleAdsProvider, "_ads_get", fake_ads_get)

    tokens = await GoogleAdsProvider().exchange_code("auth-code")

    assert seen["grant_type"] == "authorization_code"
    assert seen["code"] == "auth-code"
    assert tokens.access_token == "AT"
    assert tokens.refresh_token == "RT"  # the long-lived secret is persisted
    assert tokens.ad_account_id == "9998887776"
    assert tokens.expires_at > datetime.now(timezone.utc)


async def test_exchange_code_survives_customer_lookup_failure(real_mode, monkeypatch):
    async def fake_oauth_post(self, data):
        return {"access_token": "AT", "refresh_token": "RT", "expires_in": 3600}

    async def boom(self, url, token):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(GoogleAdsProvider, "_oauth_post", fake_oauth_post)
    monkeypatch.setattr(GoogleAdsProvider, "_ads_get", boom)

    tokens = await GoogleAdsProvider().exchange_code("c")
    assert tokens.access_token == "AT"  # degraded, not fatal


async def test_exchange_code_mock_mode_is_deterministic(mock_mode):
    tokens = await GoogleAdsProvider().exchange_code("ignored")
    assert tokens.access_token.startswith("mock-google-token-")
    assert tokens.refresh_token.startswith("mock-google-refresh-")
    assert tokens.ad_account_id == "123-456-7890"


# ── B5 / E1b(a): refresh uses the STORED REFRESH SECRET ──

async def test_refresh_tokens_uses_the_refresh_grant_never_the_access_token(
    real_mode, monkeypatch
):
    seen = {}

    async def fake_oauth_post(self, data):
        seen.update(data)
        return {"access_token": "AT2", "expires_in": 3600}

    monkeypatch.setattr(GoogleAdsProvider, "_oauth_post", fake_oauth_post)
    tokens = await GoogleAdsProvider().refresh_tokens("STORED-REFRESH-SECRET")

    assert seen["grant_type"] == "refresh_token"
    assert seen["refresh_token"] == "STORED-REFRESH-SECRET"
    # Unlike Meta, the access token is never the refresh credential.
    assert "fb_exchange_token" not in seen
    assert "code" not in seen
    assert tokens.access_token == "AT2"
    # Google reuses the same refresh secret — it is not re-issued.
    assert tokens.refresh_token is None


async def test_refresh_tokens_without_a_stored_secret_is_an_actionable_error(real_mode):
    with pytest.raises(RuntimeError, match="refresh token"):
        await GoogleAdsProvider().refresh_tokens("")


def test_refresh_tokens_docstring_contrasts_the_meta_shape():
    doc = (GoogleAdsProvider.refresh_tokens.__doc__ or "").lower()
    assert "meta" in doc
    assert "fb_exchange_token" in doc


def test_refresh_tokens_is_not_on_the_shared_abc():
    """base.py is frozen this phase — ads_push's getattr guard depends on this."""
    from apps.api.services.ads.base import AdsProvider

    assert not hasattr(AdsProvider, "refresh_tokens")


# ── C1/C2: two-API create + ingest ───────────────────────

async def test_first_push_creates_the_user_list_then_ingests_members(
    real_mode, monkeypatch
):
    ads_calls, dm_calls = [], []

    async def fake_ads_post(self, url, payload, token):
        ads_calls.append((url, payload))
        return {"results": [{"resourceName": "customers/1234567890/userLists/555"}]}

    async def fake_dm_post(self, url, payload, token):
        dm_calls.append((url, payload))
        return {"requestId": "req-abc"}

    monkeypatch.setattr(GoogleAdsProvider, "_ads_post", fake_ads_post)
    monkeypatch.setattr(GoogleAdsProvider, "_dm_post", fake_dm_post)

    result = await GoogleAdsProvider().create_or_update_audience(
        _Conn(), None, _contacts(3)
    )

    create_url, create_body = ads_calls[0]
    assert create_url.endswith(
        f"/{GOOGLE_ADS_API_VERSION}/customers/1234567890/userLists:mutate"
    )
    create_op = create_body["operations"][0]["create"]
    assert create_op["crmBasedUserList"]["uploadKeyType"] == "CONTACT_INFO"
    assert create_op["crmBasedUserList"]["dataSourceType"] == "FIRST_PARTY"

    ingest_url, ingest_body = dm_calls[0]
    assert ingest_url.endswith("/v1/audienceMembers:ingest")
    assert ingest_body["destinations"][0]["productDestinationId"] == "555"
    assert ingest_body["destinations"][0]["operatingAccount"] == {
        "accountId": "1234567890",
        "accountType": "GOOGLE_ADS",
    }

    # platform_audience_id comes from the Google Ads UserList, NEVER the
    # Data Manager requestId.
    assert result.platform_audience_id == "customers/1234567890/userLists/555"
    assert "req-abc" not in result.platform_audience_id
    assert result.pushed == 3


async def test_repeat_push_reuses_the_link_audience_id_and_skips_creation(
    real_mode, monkeypatch
):
    ads_calls, dm_calls = [], []

    async def fake_ads_post(self, url, payload, token):
        ads_calls.append(url)
        return {"results": [{"resourceName": "customers/1/userLists/999"}]}

    async def fake_dm_post(self, url, payload, token):
        dm_calls.append(payload)
        return {"requestId": "r"}

    monkeypatch.setattr(GoogleAdsProvider, "_ads_post", fake_ads_post)
    monkeypatch.setattr(GoogleAdsProvider, "_dm_post", fake_dm_post)

    result = await GoogleAdsProvider().create_or_update_audience(
        _Conn(), _Link("customers/1234567890/userLists/777"), _contacts(2)
    )

    assert result.platform_audience_id == "customers/1234567890/userLists/777"
    assert ads_calls == [], "a repeat push must NOT create a second user list"
    assert dm_calls[0]["destinations"][0]["productDestinationId"] == "777"


async def test_ingest_payload_carries_consent_and_accepted_terms(
    real_mode, monkeypatch
):
    captured = {}

    async def fake_dm_post(self, url, payload, token):
        captured.update(payload)
        return {"requestId": "r"}

    monkeypatch.setattr(GoogleAdsProvider, "_dm_post", fake_dm_post)
    contacts = _contacts(1)
    await GoogleAdsProvider().create_or_update_audience(
        _Conn(), _Link("customers/1/userLists/2"), contacts
    )

    # camelCase keys, per the live discovery document.
    assert captured["consent"] == {
        "adUserData": "CONSENT_GRANTED",
        "adPersonalization": "CONSENT_GRANTED",
    }
    assert captured["termsOfService"]["customerMatchTermsOfServiceStatus"] == "ACCEPTED"
    assert captured["encoding"] == "HEX"  # csv_exporter._sha256 emits hex
    # Only digests leave — never a plaintext identifier.
    assert captured["audienceMembers"][0]["userData"]["userIdentifiers"] == [
        {"emailAddress": contacts[0].email_sha256}
    ]


async def test_empty_contact_list_skips_the_ingest_call(real_mode, monkeypatch):
    async def fake_ads_post(self, url, payload, token):
        return {"results": [{"resourceName": "customers/1/userLists/3"}]}

    async def fake_dm_post(self, url, payload, token):
        raise AssertionError("ingest must not run for an empty contact list")

    monkeypatch.setattr(GoogleAdsProvider, "_ads_post", fake_ads_post)
    monkeypatch.setattr(GoogleAdsProvider, "_dm_post", fake_dm_post)

    result = await GoogleAdsProvider().create_or_update_audience(_Conn(), None, [])
    assert result.pushed == 0
    assert result.platform_audience_id == "customers/1/userLists/3"


async def test_missing_customer_id_fails_with_an_actionable_message(real_mode):
    with pytest.raises(RuntimeError, match="customer id"):
        await GoogleAdsProvider().create_or_update_audience(
            _Conn(ad_account_id=""), None, _contacts(1)
        )


def test_customer_id_strips_the_ui_hyphens():
    assert google_mod._customer_id(_Conn(ad_account_id="123-456-7890")) == "1234567890"


def test_user_list_id_extracts_the_bare_id():
    assert google_mod._user_list_id("customers/1/userLists/42") == "42"


async def test_developer_token_header_is_sent_on_google_ads_calls(
    real_mode, monkeypatch
):
    """Agent-probe row, made automated: the header is required on every call."""
    captured = {}

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"results": [{"resourceName": "customers/1/userLists/9"}]}

    class _Client:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            captured.update(headers or {})
            return _Resp()

    monkeypatch.setattr(google_mod.httpx, "AsyncClient", _Client)
    await GoogleAdsProvider()._ads_post("https://x.test", {}, "tok")

    assert captured["developer-token"] == "devtok"
    assert captured["Authorization"] == "Bearer tok"
    # Direct-customer access: login-customer-id is manager-only (A1b).
    assert "login-customer-id" not in captured


# ── E2 retry policy ──────────────────────────────────────

def _resp(status):
    return httpx.Response(
        status_code=status, json={}, request=httpx.Request("POST", "https://x.test")
    )


def test_only_transient_errors_are_retried():
    assert google_mod._is_transient_http_error(httpx.TimeoutException("t"))
    assert google_mod._is_transient_http_error(httpx.ConnectError("c"))
    assert google_mod._is_transient_http_error(
        httpx.HTTPStatusError("x", request=None, response=_resp(503))
    )
    assert not google_mod._is_transient_http_error(
        httpx.HTTPStatusError("x", request=None, response=_resp(400))
    )


# ── E1b(b): provider-aware credential selection at the call site ──

class _FakeDB:
    async def commit(self):
        return None


async def test_fresh_access_token_passes_the_refresh_secret_for_google(monkeypatch):
    from apps.api.services import ads_push
    from apps.api.services.ads.base import AdOAuthTokens

    seen = {}

    class _Refresher:
        async def refresh_tokens(self, credential):
            seen["credential"] = credential
            return AdOAuthTokens(
                access_token="NEW",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )

    monkeypatch.setattr(ads_push, "decrypt_token", lambda t: f"plain-{t}")
    monkeypatch.setattr(ads_push, "encrypt_token", lambda t: f"enc({t})")
    monkeypatch.setattr(ads_push, "get_provider", lambda name: _Refresher())

    conn = _Conn(access_token="enc-access")
    conn.provider = "google"
    conn.refresh_token = "enc-refresh"
    conn.token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)

    token = await ads_push.fresh_access_token(_FakeDB(), conn)

    assert seen["credential"] == "plain-enc-refresh"
    assert seen["credential"] != "plain-enc-access", "sent the access token to Google"
    assert token == "NEW"


async def test_fresh_access_token_still_passes_the_access_token_for_meta(monkeypatch):
    """Regression: the Meta path must be unchanged by the Google branch."""
    from apps.api.services import ads_push
    from apps.api.services.ads.base import AdOAuthTokens

    seen = {}

    class _Refresher:
        async def refresh_tokens(self, credential):
            seen["credential"] = credential
            return AdOAuthTokens(
                access_token="NEW",
                expires_at=datetime.now(timezone.utc) + timedelta(days=60),
            )

    monkeypatch.setattr(ads_push, "decrypt_token", lambda t: f"plain-{t}")
    monkeypatch.setattr(ads_push, "encrypt_token", lambda t: f"enc({t})")
    monkeypatch.setattr(ads_push, "get_provider", lambda name: _Refresher())

    conn = _Conn(access_token="enc-access")
    conn.provider = "meta"
    conn.refresh_token = "enc-refresh"  # present but must be ignored for Meta
    conn.token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)

    await ads_push.fresh_access_token(_FakeDB(), conn)
    assert seen["credential"] == "plain-enc-access"


async def test_google_refresh_is_skipped_when_no_refresh_secret_is_stored(monkeypatch):
    from apps.api.services import ads_push

    class _Refresher:
        async def refresh_tokens(self, credential):
            raise AssertionError("must not call refresh without a stored secret")

    monkeypatch.setattr(ads_push, "decrypt_token", lambda t: f"plain-{t}")
    monkeypatch.setattr(ads_push, "get_provider", lambda name: _Refresher())

    conn = _Conn(access_token="enc-access")
    conn.provider = "google"
    conn.refresh_token = None
    conn.token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)

    token = await ads_push.fresh_access_token(_FakeDB(), conn)
    assert token == "plain-enc-access"
    assert conn.status == "connected"
