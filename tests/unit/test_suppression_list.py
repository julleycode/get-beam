"""Phase 02 (GDPR/CCPA) unit tests — suppression list blind index + lookup.

No DB, no network. Covers the deterministic email hash (normalization +
stability) and the is_email_suppressed scope matching against a mocked session.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.api.services.pii_crypto import email_hash, normalize_email


class TestEmailHash:
    def test_normalize_lowercases_and_strips(self):
        assert normalize_email("  Foo@Bar.COM ") == "foo@bar.com"

    def test_hash_is_stable_and_case_insensitive(self):
        assert email_hash("Foo@Bar.com ") == email_hash("foo@bar.com")

    def test_hash_differs_for_different_emails(self):
        assert email_hash("a@x.com") != email_hash("b@x.com")

    def test_hash_is_hex_sha256_length(self):
        h = email_hash("a@x.com")
        assert len(h) == 64
        int(h, 16)  # raises if not hex


def _scalar_result(value) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


class TestIsEmailSuppressed:
    @pytest.mark.asyncio
    async def test_empty_email_is_never_suppressed(self):
        from apps.api.services.suppression import is_email_suppressed

        db = AsyncMock()
        assert await is_email_suppressed(db, "", "do_not_sell") is False
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_match_returns_true(self):
        from apps.api.services.suppression import is_email_suppressed

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(object()))
        assert await is_email_suppressed(db, "a@x.com", "do_not_sell") is True

    @pytest.mark.asyncio
    async def test_no_match_returns_false(self):
        from apps.api.services.suppression import is_email_suppressed

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_scalar_result(None))
        assert await is_email_suppressed(db, "a@x.com", "do_not_sell") is False
