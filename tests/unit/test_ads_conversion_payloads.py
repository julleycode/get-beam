"""G3/G12 — Meta CAPI + Google Data Manager events:ingest payload shapes."""

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from apps.api.services import ad_conversions as ac
from apps.api.services.ads.base import ConversionEvent
from apps.api.services.ads.google import (
    DM_EVENTS_BATCH_SIZE,
    GoogleAdsProvider,
    build_data_manager_event,
    build_data_manager_events_request,
    chunk_conversion_events,
)
from apps.api.services.ads.linkedin import build_linkedin_conversions_csv
from apps.api.services.ads.meta import MetaAdsProvider, build_meta_capi_event, build_meta_capi_request

pytestmark = pytest.mark.unit

EMAIL = "person@example.com"
PHONE = "(415) 555-0100"
WHEN = datetime(2026, 11, 26, 10, 30, tzinfo=timezone.utc)


def _event(**kw) -> ConversionEvent:
    base = dict(
        delivery_id=str(uuid.uuid4()),
        dedup_id="iv-123",
        conversion_type="lead",
        event_name="Lead",
        event_time=WHEN,
        email_sha256=ac.sha256_email(EMAIL),
        phone_sha256=ac.sha256_phone(PHONE, "US"),
        click_ids={"fbclid": "FBX", "fbc_ts": 1764152000000, "gclid": "GCX", "wbraid": "WB"},
        user_agent="Mozilla/5.0 (test)",
        event_source_url="https://shop.example.com/thanks",
    )
    base.update(kw)
    return ConversionEvent(**base)


def _cfg(**kw):
    base = dict(
        meta_dataset_id="ds1", meta_test_event_code=None,
        google_operating_account_id="123-456-7890", google_product_destination_id="555",
        validate_only=True, goal_event_map={"lead": "Lead"},
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_meta_event_shape_matches_documented_website_event():
    body = build_meta_capi_event(_event())
    assert body == {
        "event_name": "Lead",
        "event_time": int(WHEN.timestamp()),
        "event_id": "iv-123",
        "action_source": "website",
        "event_source_url": "https://shop.example.com/thanks",
        "user_data": {
            "client_user_agent": "Mozilla/5.0 (test)",
            "em": [hashlib.sha256(EMAIL.encode()).hexdigest()],
            "ph": [hashlib.sha256(b"14155550100").hexdigest()],
            "fbc": "fb.1.1764152000000.FBX",
        },
    }
    assert "client_ip_address" not in body["user_data"]  # D4: no raw IP v1


def test_meta_request_carries_test_event_code_only_when_set():
    assert "test_event_code" not in build_meta_capi_request(_cfg(), [_event()])
    req = build_meta_capi_request(_cfg(meta_test_event_code="TEST123"), [_event()])
    assert req["test_event_code"] == "TEST123"
    assert len(json.loads(req["data"])) == 1


def test_meta_event_omits_absent_identifiers():
    body = build_meta_capi_event(_event(phone_sha256="", click_ids={}))
    assert "ph" not in body["user_data"] and "fbc" not in body["user_data"]


def test_data_manager_event_shape():
    body = build_data_manager_event(_event())
    assert body["transactionId"] == "iv-123"
    assert body["eventTimestamp"] == "2026-11-26T10:30:00Z"
    assert body["userData"] == {
        "userIdentifiers": [
            {"emailAddress": hashlib.sha256(EMAIL.encode()).hexdigest()},
            {"phoneNumber": hashlib.sha256(b"14155550100").hexdigest()},
        ]
    }
    assert body["consent"] == {"adUserData": "CONSENT_GRANTED", "adPersonalization": "CONSENT_GRANTED"}
    assert body["adIdentifiers"] == {"gclid": "GCX"}  # exactly one, priority gclid


def test_data_manager_ad_identifier_priority_wbraid_then_gbraid():
    assert build_data_manager_event(_event(click_ids={"wbraid": "W", "gbraid": "G"}))["adIdentifiers"] == {"wbraid": "W"}
    assert build_data_manager_event(_event(click_ids={"gbraid": "G"}))["adIdentifiers"] == {"gbraid": "G"}
    assert "adIdentifiers" not in build_data_manager_event(_event(click_ids={"fbclid": "F"}))


def test_data_manager_request_destination_encoding_validate_only():
    req = build_data_manager_events_request(_cfg(), [_event()])
    assert req["destinations"] == [
        {"operatingAccount": {"accountId": "1234567890", "accountType": "GOOGLE_ADS"},
         "productDestinationId": "555"}
    ]
    assert req["encoding"] == "HEX"
    assert req["validateOnly"] is True
    assert build_data_manager_events_request(_cfg(validate_only=False), [_event()])["validateOnly"] is False


def test_data_manager_chunks_at_2000():
    assert DM_EVENTS_BATCH_SIZE == 2000
    chunks = chunk_conversion_events([_event() for _ in range(4001)])
    assert [len(c) for c in chunks] == [2000, 2000, 1]


def test_no_plaintext_pii_in_any_payload():
    ev = _event()
    blobs = [
        json.dumps(build_meta_capi_request(_cfg(), [ev])),
        json.dumps(build_data_manager_events_request(_cfg(), [ev])),
        build_linkedin_conversions_csv([ev]),
    ]
    for blob in blobs:
        assert EMAIL not in blob
        assert "4155550100" not in blob


async def test_mock_send_is_deterministic_and_makes_no_http(monkeypatch):
    from apps.api.config import settings

    monkeypatch.setattr(settings, "mock_external_apis", True)
    events = [_event(), _event()]
    for provider in (MetaAdsProvider(), GoogleAdsProvider()):
        r1 = await provider.send_conversions(None, _cfg(), events)
        r2 = await provider.send_conversions(None, _cfg(), events)
        assert [(r.delivery_id, r.ok) for r in r1] == [(r.delivery_id, r.ok) for r in r2]
        assert all(r.ok for r in r1)


async def test_meta_ua_and_event_source_url_come_from_latest_event(monkeypatch):
    monkeypatch.setattr(ac.settings, "ad_conversions_enabled", True)
    loaded = SimpleNamespace(
        visitor=SimpleNamespace(country_code="US", click_ids=None),
        identity=SimpleNamespace(country="US", phone=PHONE),
        email=EMAIL,
    )
    ok_ctx = ac.GateContext(True, True, True, True, provider="form_capture",
                            identity_status="identified", country="US", has_email=True)

    async def fake_ctx(db, s, v):
        return ok_ctx, loaded

    seen = {}

    async def fake_latest(db, s, v, at):
        seen["at"] = at
        return "https://x.com/latest", "UA-latest"

    monkeypatch.setattr(ac, "build_gate_context", fake_ctx)
    monkeypatch.setattr(ac, "_latest_event", fake_latest)
    row = SimpleNamespace(id=uuid.uuid4(), site_id="s", visitor_id="v", platform="meta",
                          conversion_type="lead", goal_id=None, dedup_id="iv-1",
                          occurred_at=WHEN)
    event, skip = await ac.prepare_event(None, row, _cfg(), WHEN + timedelta(hours=1))
    assert skip is None
    assert event.user_agent == "UA-latest" and event.event_source_url == "https://x.com/latest"
    assert seen["at"] == WHEN
    assert event.click_ids == {}


async def test_missing_ua_skips_meta_with_zero_meta_calls_google_unaffected(monkeypatch):
    monkeypatch.setattr(ac.settings, "ad_conversions_enabled", True)
    monkeypatch.setattr(ac.settings, "mock_external_apis", True)
    loaded = SimpleNamespace(
        visitor=SimpleNamespace(country_code="US", click_ids=None),
        identity=SimpleNamespace(country="US", phone=None), email=EMAIL,
    )
    ok_ctx = ac.GateContext(True, True, True, True, provider="form_capture",
                            identity_status="identified", country="US", has_email=True)

    async def fake_ctx(db, s, v):
        return ok_ctx, loaded

    async def fake_latest(db, s, v, at):
        return "https://x.com/", ""

    monkeypatch.setattr(ac, "build_gate_context", fake_ctx)
    monkeypatch.setattr(ac, "_latest_event", fake_latest)
    calls = []

    class Spy:
        async def send_conversions(self, conn, cfg, events):
            calls.append(len(events))
            return [ac.ConversionResult(delivery_id=e.delivery_id, ok=True) for e in events]

    import apps.api.services.ads.factory as factory
    import apps.api.services.ads_push as ads_push

    monkeypatch.setattr(factory, "get_provider", lambda name: Spy())

    async def fake_conn(db, s, p):
        return SimpleNamespace(status="connected")

    monkeypatch.setattr(ads_push, "get_connection", fake_conn)
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: _cfg())

    def mk(platform):
        return SimpleNamespace(id=uuid.uuid4(), site_id="s", visitor_id="v", platform=platform,
                               conversion_type="lead", goal_id=None, dedup_id="iv-1",
                               occurred_at=WHEN, status="pending", attempts=0,
                               last_error=None, next_attempt_at=None, sent_at=None)

    meta_row = mk("meta")
    stats = {"sent": 0, "failed": 0, "retry": 0, "skipped": 0}
    await ac._send_group(db, "s", "meta", [meta_row], WHEN + timedelta(hours=1), stats)
    assert meta_row.status == "skipped_no_user_agent"
    assert meta_row.last_error == "skipped_no_user_agent"
    assert calls == []
    g_row = mk("google")
    await ac._send_group(db, "s", "google", [g_row], WHEN + timedelta(hours=1), stats)
    assert g_row.status == "sent" and calls == [1]


def test_linkedin_csv_columns():
    csv_text = build_linkedin_conversions_csv([_event(click_ids={"li_fat_id": "LI"})])
    header, line = csv_text.strip().splitlines()
    assert header == "email_sha256,li_fat_id,conversion_type,event_name,event_time,dedup_id"
    assert ",LI,lead,Lead,2026-11-26T10:30:00Z,iv-123" in line
