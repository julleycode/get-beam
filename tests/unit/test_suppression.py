"""Suppression compliance tests (do_not_email).

Unit tests: mock DB, no network. Covers:
- EmailSender.send() skips suppressed recipients (and only when a db session
  is provided — transactional sends without a session are unchanged).
- Suppression lookup is case-insensitive and filters on do_not_email IS TRUE.
- CSV audience export query excludes do_not_email contacts.
- Email masking helper never logs the full address.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.services.csv_exporter import _get_segment_visitors
from apps.api.services.email_sender import EmailSender, _mask_email


def _make_db(execute_results: list) -> AsyncMock:
    """AsyncSession mock whose execute() returns the given results in order."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=execute_results)
    return db


def _scalar_result(value) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _scalars_all_result(values: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


def _mock_sendgrid(client_cls: MagicMock, status_code: int = 202) -> AsyncMock:
    """Wire a mocked httpx.AsyncClient class; returns the inner client mock."""
    response = MagicMock(status_code=status_code, text="")
    response.headers = {"X-Message-Id": "msg-123"}
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    client_cls.return_value.__aenter__ = AsyncMock(return_value=client)
    client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return client


class TestMaskEmail:
    def test_masks_local_part(self):
        assert _mask_email("johndoe@example.com") == "jo***@example.com"

    def test_never_contains_full_local_part(self):
        masked = _mask_email("sensitive.person@example.com")
        assert "sensitive.person" not in masked
        assert masked.endswith("@example.com")

    def test_handles_missing_domain(self):
        assert _mask_email("oops") == "oo***"


class TestEmailSenderSuppression:
    @pytest.mark.asyncio
    async def test_send_skips_suppressed_recipient(self):
        db = _make_db([_scalar_result(uuid.uuid4())])  # suppressed row found

        with patch("apps.api.services.email_sender.httpx.AsyncClient") as client_cls:
            client = _mock_sendgrid(client_cls)
            result = await EmailSender().send(
                to_email="optout@example.com",
                subject="hi",
                body_html="<p>hi</p>",
                unsubscribe_url="https://x.test/u?t=abc",
                db=db,
            )

        assert result is None  # falsy skip result
        client.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_skips_when_on_suppression_list(self):
        # Flag query finds no row, but the suppression list does → must skip.
        db = _make_db([_scalar_result(None), _scalar_result(uuid.uuid4())])
        with patch("apps.api.services.email_sender.httpx.AsyncClient") as client_cls:
            client = _mock_sendgrid(client_cls)
            result = await EmailSender().send(
                to_email="optout@example.com",
                subject="hi",
                body_html="<p>hi</p>",
                unsubscribe_url="https://x.test/u?t=abc",
                db=db,
            )
        assert result is None
        client.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_proceeds_when_not_suppressed(self):
        db = _make_db([_scalar_result(None), _scalar_result(None)])  # flag none; list none

        with patch("apps.api.services.email_sender.httpx.AsyncClient") as client_cls:
            client = _mock_sendgrid(client_cls)
            result = await EmailSender().send(
                to_email="ok@example.com",
                subject="hi",
                body_html="<p>hi</p>",
                unsubscribe_url="https://x.test/u?t=abc",
                db=db,
            )

        assert result == {"id": "msg-123", "status": 202}
        client.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_without_db_skips_check_and_sends(self):
        """Transactional callers (no session) keep the existing behavior."""
        with patch("apps.api.services.email_sender.httpx.AsyncClient") as client_cls:
            client = _mock_sendgrid(client_cls)
            result = await EmailSender().send(
                to_email="signup@example.com",
                subject="hi",
                body_html="<p>hi</p>",
                unsubscribe_url="https://x.test/u?t=abc",
            )

        assert result == {"id": "msg-123", "status": 202}
        client.post.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_suppression_lookup_is_case_insensitive(self):
        """Mixed-case recipient must match lower() on both sides."""
        db = _make_db([_scalar_result(None), _scalar_result(None)])
        await EmailSender()._is_suppressed(db, "  MixedCase@Example.COM ")

        stmt = db.execute.call_args_list[0].args[0]
        compiled = str(stmt)
        assert "lower(" in compiled.lower()
        assert "do_not_email IS true" in compiled
        # Bound param must be the normalized (stripped + lowercased) email
        assert "mixedcase@example.com" in stmt.compile().params.values()


class TestCsvExportSuppression:
    @pytest.mark.asyncio
    async def test_export_query_filters_do_not_email(self):
        member = SimpleNamespace(site_id="s1", visitor_id="v1")
        db = _make_db([
            _scalars_all_result([member]),
            _scalar_result(None),  # DB filtered the suppressed row out
        ])

        visitors = await _get_segment_visitors(db, "seg-1")

        assert visitors == []
        identified_stmt = db.execute.call_args_list[1].args[0]
        assert "do_not_email IS NOT" in str(identified_stmt)

    @pytest.mark.asyncio
    async def test_export_includes_non_suppressed_contact(self):
        member = SimpleNamespace(site_id="s1", visitor_id="v1")
        identified = SimpleNamespace(
            email="Lead@Example.com",
            full_name="Ann Lee",
            phone=None,
            city=None,
            region=None,
            country=None,
            resolution_provider="form_capture",  # first-party → exportable
        )
        db = _make_db([
            _scalars_all_result([member]),
            _scalar_result(identified),
            _scalar_result(None),  # suppression list: not on do_not_sell
            _scalar_result(None),  # no enrichment profile
        ])

        visitors = await _get_segment_visitors(db, "seg-1")

        assert len(visitors) == 1
        assert visitors[0]["email"] == "Lead@Example.com"
        assert visitors[0]["first_name"] == "Ann"
        assert visitors[0]["last_name"] == "Lee"

    @pytest.mark.asyncio
    async def test_export_excludes_company_level_identity(self):
        # hunter/apollo return a random employee at the visitor's company — never
        # export that to ad audiences / CRM.
        member = SimpleNamespace(site_id="s1", visitor_id="v1")
        identified = SimpleNamespace(
            email="random.employee@acme.com",
            full_name="Random Employee",
            phone=None,
            city=None,
            region=None,
            country=None,
            resolution_provider="hunter",  # company-level guess
        )
        db = _make_db([
            _scalars_all_result([member]),
            _scalar_result(identified),
        ])

        visitors = await _get_segment_visitors(db, "seg-1")
        assert visitors == []
