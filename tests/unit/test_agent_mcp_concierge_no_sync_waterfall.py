"""MF-3 (VALIDATE-added, Fully-Automated) — the budget-exhaustion guardrail.

The single most important security property of the WS3 conversion tool: it MUST
NEVER synchronously invoke the paid identity-resolution waterfall
(``IdentityResolver.resolve`` / ``run_company_resolution_sweep``) from the public,
unauthenticated request/response cycle. Doing so would let an unauthenticated
caller drain a site's entire 50/day identity-resolution budget via repeated
``request_quote`` calls.

Pure monkeypatch / call-count assertion — no live DB, no network. Proves the code
path structurally cannot reach the paid waterfall: every paid provider entry
point is patched to raise-if-called, and the conversion tool still completes.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import apps.api.main  # noqa: F401 — registers every ORM model

pytestmark = pytest.mark.unit


def _mock_db():
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()
    owner_row = MagicMock()
    owner_row.first.return_value = ("owner@example.com",)
    db.execute = AsyncMock(return_value=owner_row)
    return db


async def test_request_quote_never_calls_paid_waterfall(monkeypatch):
    from apps.api.services import agent_gateway
    from apps.api.services import company_resolver
    from apps.api.services.email_sender import EmailSender
    from apps.api.services.identity_resolver import IdentityResolver

    # Every paid-provider entry point: raise the instant it is called.
    def _boom(*a, **k):
        raise AssertionError("paid identity-resolution waterfall was invoked")

    monkeypatch.setattr(IdentityResolver, "resolve", _boom, raising=False)
    monkeypatch.setattr(
        "apps.api.services.agent_company_resolution.run_company_resolution_sweep",
        _boom,
        raising=False,
    )

    # The FREE path is what the conversion tool must use. Record that it is the
    # only resolver called, and that it receives the db (free graph read path).
    free_calls: list = []

    async def _free(ip, db=None):
        free_calls.append((ip, db))
        return "acme.example"

    monkeypatch.setattr(company_resolver, "resolve_company_cached", _free)

    # Never actually send email.
    monkeypatch.setattr(EmailSender, "send", AsyncMock(return_value={"id": "x"}))

    db = _mock_db()
    site = SimpleNamespace(site_id="site-1", user_id="u-1")
    profile = SimpleNamespace(qualified_content={})

    result = await agent_gateway.handle_conversion_tool(
        db,
        site,
        profile,
        "request_quote",
        {
            "use_case": "analytics",
            "company_size": "50-200",
            "evaluating_against": "clay",
        },
        ip_address="203.0.113.7",
    )

    # Completed via the FREE path only.
    assert result["lead_created"] is True
    assert len(free_calls) == 1
    assert free_calls[0][0] == "203.0.113.7"
    # A lead row was added and committed.
    assert db.add.called


async def test_free_resolution_failure_still_creates_lead(monkeypatch):
    """Even if the free lookup raises, the lead is still written (fail-open) and
    the paid waterfall is never reached."""
    from apps.api.services import agent_gateway
    from apps.api.services import company_resolver
    from apps.api.services.email_sender import EmailSender
    from apps.api.services.identity_resolver import IdentityResolver

    monkeypatch.setattr(
        IdentityResolver,
        "resolve",
        MagicMock(side_effect=AssertionError("paid waterfall invoked")),
        raising=False,
    )

    async def _free_boom(ip, db=None):
        raise RuntimeError("rDNS blew up")

    monkeypatch.setattr(company_resolver, "resolve_company_cached", _free_boom)
    monkeypatch.setattr(EmailSender, "send", AsyncMock(return_value={"id": "x"}))

    db = _mock_db()
    site = SimpleNamespace(site_id="site-1", user_id="u-1")
    profile = SimpleNamespace(qualified_content={})

    result = await agent_gateway.handle_conversion_tool(
        db,
        site,
        profile,
        "book_demo",
        {"use_case": "x", "company_size": "y", "evaluating_against": "z"},
        ip_address="203.0.113.7",
    )

    assert result["lead_created"] is True
    assert db.add.called


async def test_missing_params_returns_needs_more_info_no_lead(monkeypatch):
    from apps.api.services import agent_gateway

    db = _mock_db()
    site = SimpleNamespace(site_id="site-1", user_id="u-1")
    profile = SimpleNamespace(qualified_content={})

    result = await agent_gateway.handle_conversion_tool(
        db, site, profile, "request_quote", {"use_case": "only-one"}, ip_address=None
    )

    assert result["needs_more_info"] is True
    assert set(result["missing_params"]) == {"company_size", "evaluating_against"}
    # No lead written when qualification is incomplete.
    assert not db.add.called
