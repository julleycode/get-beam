"""MF-3 (VALIDATE-added, Fully-Automated) — the budget-exhaustion guardrail.

The WS3 conversion tool MUST NEVER invoke the paid identity-resolution waterfall
(``IdentityResolver.resolve`` / ``run_company_resolution_sweep``) on behalf of a
public, unauthenticated caller.

After the review-fix cycle the request path (``handle_conversion_tool``) is
DB-only and does no company lookup at all; the lookup moved to the background
task ``process_new_lead``, which uses the FREE cached path with ``db=None`` (no
cross-tenant company_graph write). Both halves are asserted here.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import apps.api.main  # noqa: F401 — registers every ORM model
from apps.api.config import settings
from tests.unit._agent_concierge_fakes import FakeRedis, FakeSession, make_lead
from tests.unit._agent_concierge_fakes import mock_db as _mock_db

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _hermetic_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr("apps.api.services.redis_client.get_redis", lambda: fake)
    return fake


def _patch_paid(monkeypatch):
    from apps.api.services.identity_resolver import IdentityResolver

    def _boom(*a, **k):
        raise AssertionError("paid identity-resolution waterfall was invoked")

    monkeypatch.setattr(IdentityResolver, "resolve", _boom, raising=False)
    monkeypatch.setattr(
        "apps.api.services.agent_company_resolution.run_company_resolution_sweep",
        _boom,
        raising=False,
    )


async def test_request_path_never_resolves_company(monkeypatch):
    """The request path is DB-only: no lookup of any kind (free or paid)."""
    from apps.api.services import agent_gateway, company_resolver

    _patch_paid(monkeypatch)

    async def _free(ip, db=None):
        raise AssertionError("company lookup ran on the request path")

    monkeypatch.setattr(company_resolver, "resolve_company_cached", _free)

    db = _mock_db()
    site = SimpleNamespace(site_id="site-1", user_id="u-1")
    result, lead_id = await agent_gateway.handle_conversion_tool(
        db,
        site,
        SimpleNamespace(qualified_content={}),
        "request_quote",
        {"use_case": "analytics", "company_size": "50-200", "evaluating_against": "clay"},
        ip_address="203.0.113.7",
    )
    assert result["lead_created"] is True
    assert lead_id is not None
    lead = db.add.call_args[0][0]
    assert lead.resolved_company_domain is None
    assert lead.ip_address == "203.0.113.0"  # /24 prefix, never the full IP


async def test_background_task_uses_free_path_without_db(monkeypatch):
    from apps.api.services import agent_gateway, company_resolver
    from apps.api.services.email_sender import EmailSender

    _patch_paid(monkeypatch)
    monkeypatch.setattr(settings, "mock_external_apis", False)
    free_calls: list = []

    async def _free(ip, db=None):
        free_calls.append((ip, db))
        return "acme.example"

    monkeypatch.setattr(company_resolver, "resolve_company_cached", _free)
    monkeypatch.setattr(EmailSender, "send", AsyncMock(return_value={"id": "x"}))

    lead = make_lead(1)
    sess = FakeSession(lead, SimpleNamespace(site_id="site-1", user_id="u-1"))
    monkeypatch.setattr("apps.api.models.database.async_session", lambda: sess)

    await agent_gateway.process_new_lead(lead.id, "203.0.113.7")

    assert free_calls == [("203.0.113.7", None)]  # db=None: no graph write
    assert lead.resolved_company_domain == "acme.example"
    assert lead.notified is True
    assert sess.commits == 1


async def test_free_resolution_failure_still_notifies(monkeypatch):
    from apps.api.services import agent_gateway, company_resolver
    from apps.api.services.email_sender import EmailSender

    _patch_paid(monkeypatch)
    monkeypatch.setattr(settings, "mock_external_apis", False)

    async def _free_boom(ip, db=None):
        raise RuntimeError("rDNS blew up")

    monkeypatch.setattr(company_resolver, "resolve_company_cached", _free_boom)
    send = AsyncMock(return_value={"id": "x"})
    monkeypatch.setattr(EmailSender, "send", send)

    lead = make_lead(2, tool_name="book_demo")
    sess = FakeSession(lead, SimpleNamespace(site_id="site-1", user_id="u-1"))
    monkeypatch.setattr("apps.api.models.database.async_session", lambda: sess)

    await agent_gateway.process_new_lead(lead.id, "203.0.113.7")
    assert lead.resolved_company_domain is None
    assert send.await_count == 1
    assert lead.notified is True


async def test_missing_params_returns_needs_more_info_no_lead(monkeypatch):
    from apps.api.services import agent_gateway

    db = _mock_db()
    site = SimpleNamespace(site_id="site-1", user_id="u-1")
    profile = SimpleNamespace(qualified_content={})

    result, lead_id = await agent_gateway.handle_conversion_tool(
        db, site, profile, "request_quote", {"use_case": "only-one"}, ip_address=None
    )

    assert lead_id is None
    assert result["needs_more_info"] is True
    assert set(result["missing_params"]) == {"company_size", "evaluating_against"}
    assert not db.add.called
