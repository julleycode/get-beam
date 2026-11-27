"""G2/G8 — fail-closed consent gate matrix, dedup, allow-list, stale guard."""

import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from apps.api.services import ad_conversions as ac

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)


def _ok_ctx() -> ac.GateContext:
    return ac.GateContext(
        flag_enabled=True, site_exists=True, visitor_exists=True, identity_exists=True,
        provider="form_capture", identity_status="identified", country="US", has_email=True,
    )


def test_passing_context_has_no_skip():
    assert ac.evaluate_gates(_ok_ctx()) is None


@pytest.mark.parametrize(
    "change,expected",
    [
        ({"flag_enabled": False}, ac.SKIP_FLAG_OFF),
        ({"site_exists": False}, ac.SKIP_ERASED),
        ({"visitor_exists": False}, ac.SKIP_ERASED),
        ({"identity_exists": False}, ac.SKIP_ERASED),
        ({"do_not_resolve": True}, ac.SKIP_DO_NOT_RESOLVE),
        ({"source_agent_visit_id": "agent-1"}, ac.SKIP_AGENT_ORIGIN),
        ({"is_abuse_flagged": True}, ac.SKIP_ABUSE),
        ({"is_bot_suspect": True}, ac.SKIP_BOT),
        ({"internal_override": "internal"}, ac.SKIP_INTERNAL),
        ({"is_internal_suspect": True}, ac.SKIP_INTERNAL),
        ({"provider": "rb2b"}, ac.SKIP_NOT_FIRST_PARTY),
        ({"provider": "hunter"}, ac.SKIP_NOT_FIRST_PARTY),
        ({"identity_status": "candidate"}, ac.SKIP_NOT_FIRST_PARTY),
        ({"do_not_email": True}, ac.SKIP_DO_NOT_EMAIL),
        ({"suppressed": True}, ac.SKIP_SUPPRESSED),
        ({"country": "DE"}, ac.SKIP_EEA),
        ({"country": "no"}, ac.SKIP_EEA),
        ({"country": None}, ac.SKIP_EEA),
        ({"country": ""}, ac.SKIP_EEA),
        ({"company_excluded": True}, ac.SKIP_COMPANY_EXCLUDED),
        ({"has_email": False}, ac.SKIP_NO_IDENTIFIER),
    ],
)
def test_should_skip_conversion_for_each_fail_closed_gate(change, expected):
    assert ac.evaluate_gates(replace(_ok_ctx(), **change)) == expected


def test_internal_suspect_cleared_by_explicit_not_internal_override():
    ctx = replace(_ok_ctx(), is_internal_suspect=True, internal_override="not_internal")
    assert ac.evaluate_gates(ctx) is None


def test_first_party_providers_exact_membership_pinned():
    assert ac.FIRST_PARTY_PROVIDERS == frozenset({"form_capture", "pdl_person_enrich"})


@pytest.mark.parametrize(
    "provider",
    ["rb2b", "leadpipe", "capturify", "beam_identity_network", "hunter", "apollo",
     "fingerprint_match", "svid_reconcile", "fingerprint", "email_click", "manual",
     "contact_import", None, ""],
)
def test_non_first_party_providers_never_qualify(provider):
    assert not ac.is_first_party_identity(provider, "identified", None, False)


def test_first_party_requires_identified_and_emailable():
    assert ac.is_first_party_identity("pdl_person_enrich", "identified", None, False)
    assert not ac.is_first_party_identity("form_capture", "candidate", None, False)
    assert not ac.is_first_party_identity("form_capture", "identified", "agent", False)
    assert not ac.is_first_party_identity("form_capture", "identified", None, True)


@pytest.mark.parametrize(
    "raw,country,expected",
    [
        ("(415) 555-0100", "US", "14155550100"),
        ("+44 20 7946 0958", None, "442079460958"),
        ("0044 20 7946 0958", None, "442079460958"),
        ("020 7946 0958", "GB", "442079460958"),
        ("5550100", "ZZ", None),
        ("123", "US", None),
        ("+1234567890123456", None, None),
        ("", "US", None),
        (None, "US", None),
    ],
)
def test_normalize_phone_e164(raw, country, expected):
    assert ac.normalize_phone_e164(raw, country) == expected


def test_hashes_are_sha256_hex_of_normalized_values():
    import hashlib

    assert ac.sha256_email("  A@B.com ") == hashlib.sha256(b"a@b.com").hexdigest()
    assert ac.sha256_email(None) == ""
    assert ac.sha256_phone("(415) 555-0100", "US") == hashlib.sha256(b"14155550100").hexdigest()
    assert ac.sha256_phone("123", "US") == ""


def test_backoff_is_capped_exponential():
    assert [ac.backoff_seconds(n) for n in (0, 1, 2, 5, 6, 20)] == [60, 120, 240, 1920, 3600, 3600]


async def test_flag_off_enqueue_writes_zero_rows(monkeypatch):
    monkeypatch.setattr(ac.settings, "ad_conversions_enabled", False)
    db = AsyncMock()
    status = await ac.enqueue_conversion(
        db, "s", "v", "lead", platform="meta", dedup_id="d", occurred_at=NOW
    )
    assert status is None
    db.execute.assert_not_called()


async def test_enqueue_uses_given_dedup_id_with_on_conflict_do_nothing(monkeypatch):
    monkeypatch.setattr(ac.settings, "ad_conversions_enabled", True)

    async def fake_ctx(db, site_id, visitor_id):
        return _ok_ctx(), None

    monkeypatch.setattr(ac, "build_gate_context", fake_ctx)
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(rowcount=1)
    dedup = str(uuid.uuid4())
    for _ in range(2):  # stable across retries: same dedup id each time
        await ac.enqueue_conversion(
            db, "s", "v", "lead", platform="meta", dedup_id=dedup, occurred_at=NOW
        )
    stmts = [c.args[0] for c in db.execute.call_args_list]
    compiled = [str(s.compile()) for s in stmts]
    assert all("ON CONFLICT ON CONSTRAINT uq_ad_conv_delivery_dedup DO NOTHING" in c for c in compiled)
    params = [s.compile().params for s in stmts]
    assert params[0]["dedup_id"] == params[1]["dedup_id"] == dedup
    assert params[0]["status"] == "pending"


async def test_enqueue_unmapped_goal_records_skipped_unmapped(monkeypatch):
    monkeypatch.setattr(ac.settings, "ad_conversions_enabled", True)
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(rowcount=1)
    status = await ac.enqueue_conversion(
        db, "s", "v", "goal", platform="meta", dedup_id="c1", occurred_at=NOW, mapped=False
    )
    assert status == ac.SKIP_UNMAPPED


# ── G8: Meta stale guard ──


def _row(platform="meta", age=timedelta(hours=1)):
    return SimpleNamespace(
        id=uuid.uuid4(), site_id="s", visitor_id="v", platform=platform,
        conversion_type="lead", goal_id=None, dedup_id="iv-1", occurred_at=NOW - age,
    )


def _cfg():
    return SimpleNamespace(
        goal_event_map={"lead": "Lead"}, meta_dataset_id="ds1", meta_test_event_code=None,
        google_operating_account_id="123", google_product_destination_id="999",
        validate_only=True,
    )


def _patch_ctx(monkeypatch, ua="Mozilla/5.0"):
    loaded = SimpleNamespace(
        visitor=SimpleNamespace(country_code="US", click_ids={"fbclid": "F", "fbc_ts": 1}),
        identity=SimpleNamespace(country="US", phone=None),
        email="a@b.com",
    )

    async def fake_ctx(db, site_id, visitor_id):
        return _ok_ctx(), loaded

    async def fake_latest(db, site_id, visitor_id, at):
        return "https://x.com/thanks", ua

    monkeypatch.setattr(ac, "build_gate_context", fake_ctx)
    monkeypatch.setattr(ac, "_latest_event", fake_latest)


async def test_stale_meta_row_older_than_6_days_is_skipped_stale(monkeypatch):
    monkeypatch.setattr(ac.settings, "ad_conversions_enabled", True)
    _patch_ctx(monkeypatch)
    event, skip = await ac.prepare_event(None, _row(age=timedelta(days=6, minutes=1)), _cfg(), NOW)
    assert event is None and skip == ac.SKIP_STALE
    fresh, skip2 = await ac.prepare_event(None, _row(age=timedelta(days=5)), _cfg(), NOW)
    assert skip2 is None and fresh is not None


async def test_stale_guard_is_meta_only(monkeypatch):
    monkeypatch.setattr(ac.settings, "ad_conversions_enabled", True)
    _patch_ctx(monkeypatch)
    event, skip = await ac.prepare_event(
        None, _row(platform="google", age=timedelta(days=10)), _cfg(), NOW
    )
    assert skip is None and event is not None


async def test_stale_batch_remaining_rows_still_send(monkeypatch):
    """A >6d row is skipped and the rest of the batch still reaches the provider."""
    monkeypatch.setattr(ac.settings, "ad_conversions_enabled", True)
    monkeypatch.setattr(ac.settings, "mock_external_apis", True)
    _patch_ctx(monkeypatch)
    sent_batches: list = []

    class FakeProvider:
        async def send_conversions(self, conn, cfg, events):
            sent_batches.append(events)
            return [ac.ConversionResult(delivery_id=e.delivery_id, ok=True) for e in events]

    import apps.api.services.ads.factory as factory
    import apps.api.services.ads_push as ads_push

    monkeypatch.setattr(factory, "get_provider", lambda name: FakeProvider())

    async def fake_conn(db, site_id, provider):
        return SimpleNamespace(status="connected")

    monkeypatch.setattr(ads_push, "get_connection", fake_conn)
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: _cfg())
    stale, fresh = _row(age=timedelta(days=7)), _row(age=timedelta(hours=2))
    for r in (stale, fresh):
        r.status, r.attempts, r.last_error, r.next_attempt_at, r.sent_at = "pending", 0, None, None, None
    stats = {"sent": 0, "failed": 0, "retry": 0, "skipped": 0}
    await ac._send_group(db, "s", "meta", [stale, fresh], NOW, stats)
    assert stale.status == ac.SKIP_STALE
    assert fresh.status == "sent"
    assert len(sent_batches) == 1 and len(sent_batches[0]) == 1
