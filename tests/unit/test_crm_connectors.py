"""Unit tests for CRM connectors + contact mapper (no DB, no network).

Network paths are exercised in mock mode (settings.mock_external_apis); the
HMAC signature is verified directly.
"""

import hashlib
import hmac
import json

import pytest

from apps.api.services.crm import get_crm_connector, supported_providers
from apps.api.services.crm.base import CRMContact, PushResult
from apps.api.services.crm.contact_mapper import rows_to_contacts, visitor_to_contact
from apps.api.services.crm.generic_webhook import _sign
from apps.api.services.crm.hubspot import _to_properties

pytestmark = pytest.mark.unit


def test_factory_known_providers():
    assert supported_providers() == {
        "generic_webhook",
        "hubspot",
        "pipedrive",
        "salesforce",
    }
    assert get_crm_connector("hubspot").auth_type == "oauth"
    assert get_crm_connector("pipedrive").auth_type == "oauth"
    assert get_crm_connector("salesforce").auth_type == "oauth"
    assert get_crm_connector("generic_webhook").auth_type == "webhook"


def test_factory_rejects_unknown():
    with pytest.raises(ValueError):
        get_crm_connector("mailchimp")


def test_contact_mapper_default():
    row = {"email": "a@b.com", "first_name": "Ada", "company_name": "Acme"}
    c = visitor_to_contact(row)
    assert c.email == "a@b.com"
    assert c.first_name == "Ada"
    assert c.company_name == "Acme"
    assert c.last_name == ""  # missing keys default to empty, not None


def test_contact_mapper_field_mapping_override():
    # Map the CRM "company_name" attr onto a different source key.
    row = {"email": "a@b.com", "org": "Globex"}
    c = visitor_to_contact(row, {"company_name": "org"})
    assert c.company_name == "Globex"


def test_rows_to_contacts_batch():
    rows = [{"email": "a@b.com"}, {"email": "c@d.com"}]
    contacts = rows_to_contacts(rows)
    assert [c.email for c in contacts] == ["a@b.com", "c@d.com"]


def test_hubspot_property_mapping_skips_blanks():
    props = _to_properties(CRMContact(email="a@b.com", first_name="Ada", region="CA"))
    assert props == {"email": "a@b.com", "firstname": "Ada", "state": "CA"}


def test_webhook_signature_is_hmac_sha256():
    body = json.dumps({"type": "ping"}).encode()
    expected = hmac.new(b"secret123", body, hashlib.sha256).hexdigest()
    assert _sign("secret123", body) == expected


async def test_mock_mode_push_and_test(monkeypatch):
    from apps.api.config import settings

    monkeypatch.setattr(settings, "mock_external_apis", True)
    contacts = [CRMContact(email="a@b.com"), CRMContact(email="c@d.com")]
    for provider in ("generic_webhook", "hubspot", "pipedrive", "salesforce"):
        conn = get_crm_connector(provider)
        assert await conn.test_connection(
            access_token="t", webhook_url="https://x", secret="secret12", instance_url="https://i"
        ) is True
        result: PushResult = await conn.upsert_contacts(
            contacts,
            access_token="t",
            webhook_url="https://x",
            secret="secret12",
            instance_url="https://i",
        )
        assert result.pushed == 2
        assert result.failed == 0


async def test_mock_mode_oauth_exchange(monkeypatch):
    from apps.api.config import settings

    monkeypatch.setattr(settings, "mock_external_apis", True)
    expected = {
        "hubspot": "mock_hubspot_token",
        "pipedrive": "mock_pipedrive_token",
        "salesforce": "mock_salesforce_token",
    }
    for provider, token in expected.items():
        tokens = await get_crm_connector(provider).exchange_code("code")
        assert tokens.access_token == token
        assert tokens.refresh_token
    # Pipedrive/Salesforce carry a per-account base URL.
    assert (await get_crm_connector("pipedrive").exchange_code("c")).external_account_id
    assert (await get_crm_connector("salesforce").exchange_code("c")).external_account_id


async def test_generic_webhook_not_oauth():
    with pytest.raises(NotImplementedError):
        await get_crm_connector("generic_webhook").get_auth_url("state")


class _FakeDB:
    """Minimal stand-in that flags whether the query path was touched."""

    def __init__(self):
        self.executed = False

    async def execute(self, *_args, **_kwargs):
        self.executed = True
        raise AssertionError("auto_push should not query the DB when gated off")


async def test_auto_push_disabled_is_noop(monkeypatch):
    from apps.api.config import settings
    from apps.api.services.crm_push import auto_push_segments

    monkeypatch.setattr(settings, "crm_auto_push", False)
    db = _FakeDB()
    await auto_push_segments(db, "site-1", ["seg-1"])  # must return without touching db
    assert db.executed is False


async def test_auto_push_empty_segments_is_noop(monkeypatch):
    from apps.api.config import settings
    from apps.api.services.crm_push import auto_push_segments

    monkeypatch.setattr(settings, "crm_auto_push", True)
    db = _FakeDB()
    await auto_push_segments(db, "site-1", [])  # no segments → no work
    assert db.executed is False


async def test_push_rate_limiter_fails_open_without_redis():
    # No Redis in the unit env → the limiter must fail OPEN (return True) rather
    # than block every push.
    from apps.api.services.crm_rate_limiter import check_and_reserve_push

    assert await check_and_reserve_push("site-1") is True


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://8.8.8.8/hook", True),       # public IP literal — no DNS needed
        ("http://127.0.0.1/x", False),        # loopback
        ("http://169.254.169.254/meta", False),  # cloud metadata (link-local)
        ("http://10.1.2.3/hook", False),      # private
        ("http://192.168.0.5/", False),       # private
        ("http://0.0.0.0/", False),           # unspecified
        ("http://[::1]/", False),             # ipv6 loopback
        ("ftp://8.8.8.8/", False),            # non-http scheme
        ("https://", False),                  # no host
        ("not a url", False),
    ],
)
async def test_ssrf_url_guard(url, expected):
    from apps.api.services.url_guard import is_safe_public_url

    assert await is_safe_public_url(url) is expected


async def test_generic_webhook_rejects_private_url(monkeypatch):
    from apps.api.config import settings

    monkeypatch.setattr(settings, "mock_external_apis", False)
    conn = get_crm_connector("generic_webhook")
    assert await conn.test_connection(webhook_url="http://127.0.0.1/x", secret="secret12") is False
    res = await conn.upsert_contacts(
        [CRMContact(email="a@b.com")], webhook_url="http://169.254.169.254/x", secret="secret12"
    )
    assert res.pushed == 0 and res.failed == 1
