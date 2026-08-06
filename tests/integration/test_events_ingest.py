"""Integration tests for the event ingestion endpoint.

Requires: PostgreSQL + Redis running locally (via docker-compose).
Uses test_client and test_db from conftest.py which auto-create tables.
"""

import json

import pytest
import pytest_asyncio
from sqlalchemy import select

# Realistic browser UA to avoid bot filter (is_bot returns True for empty UA)
_BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def test_site_id(test_db):
    """Create a test site using ORM and return its site_id."""
    from apps.api.models.user import User
    from apps.api.models.site import Site

    # Ensure test user
    result = await test_db.execute(select(User).where(User.email == "test-ingest@test.com"))
    user = result.scalar_one_or_none()
    if not user:
        user = User(email="test-ingest@test.com", full_name="Test User")
        test_db.add(user)
        await test_db.flush()

    site_id = "test_site_ingest"
    result = await test_db.execute(select(Site).where(Site.site_id == site_id))
    if not result.scalar_one_or_none():
        test_db.add(Site(site_id=site_id, user_id=user.id, name="Test Site", url="https://test-ingest.example.com"))
        await test_db.flush()

    await test_db.commit()
    return site_id


class TestEventIngestion:
    """Test POST /api/v1/events/ingest"""

    @pytest.mark.asyncio
    async def test_valid_batch_returns_204(self, test_client, test_site_id):
        """Valid event batch should return 204 No Content."""
        payload = {
            "site_id": test_site_id,
            "visitor_id": "test-visitor-001",
            "events": [
                {
                    "type": "pageview",
                    "url": "https://test-ingest.example.com/",
                    "page_path": "/",
                    "page_title": "Home",
                    "user_agent": "Mozilla/5.0 Chrome/120.0.0.0",
                    "ts": "2026-05-27T00:00:00",
                }
            ],
        }
        resp = await test_client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_bot_ua_returns_204_silently(self, test_client, test_site_id):
        """Bot user-agents should be silently discarded (not 400/403)."""
        payload = {
            "site_id": "any-site",
            "visitor_id": "bot-visitor",
            "events": [
                {
                    "type": "pageview",
                    "url": "https://example.com/",
                    "ts": "2026-05-27T00:00:00",
                }
            ],
        }
        resp = await test_client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Googlebot/2.1 (+http://www.google.com/bot.html)",
            },
        )
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_invalid_site_returns_403(self, test_client, test_site_id):
        """Non-existent site_id should return 403."""
        payload = {
            "site_id": "nonexistent_site_12345",
            "visitor_id": "test-visitor",
            "events": [
                {
                    "type": "pageview",
                    "url": "https://example.com/",
                    "ts": "2026-05-27T00:00:00",
                }
            ],
        }
        resp = await test_client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_deleted_site_403_expires_svid_cookie(self, test_client, test_site_id):
        """A deleted/unknown site returns 403 AND expires the durable HttpOnly
        _rta_svid_<site> cookie (only the server can clear an HttpOnly cookie),
        so a returning visitor's browser drops it. The pixel clears its own
        client cookies when it reads the 403."""
        site_id = "nonexistent_site_99999"
        payload = {
            "site_id": site_id,
            "visitor_id": "test-visitor",
            "events": [
                {
                    "type": "pageview",
                    "url": "https://example.com/",
                    "ts": "2026-05-27T00:00:00",
                }
            ],
        }
        resp = await test_client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={"Content-Type": "text/plain", "User-Agent": _BROWSER_UA},
        )
        assert resp.status_code == 403
        set_cookies = resp.headers.get_list("set-cookie")
        svid = [c for c in set_cookies if "_rta_svid_nonexistent_site_99999" in c]
        assert svid, f"expected svid expiry Set-Cookie, got {set_cookies}"
        # Expired: Starlette delete_cookie emits Max-Age=0 + the 1970 epoch expiry.
        assert "Max-Age=0" in svid[0] or "01 Jan 1970" in svid[0], svid[0]

    @pytest.mark.asyncio
    async def test_malformed_json_returns_400(self, test_client, test_site_id):
        """Malformed JSON should return 400."""
        resp = await test_client.post(
            "/api/v1/events/ingest",
            content="not-json{{{",
            headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_text_plain_content_type_works(self, test_client, test_site_id):
        """text/plain should work (sendBeacon uses this for CORS)."""
        payload = {
            "site_id": test_site_id,
            "visitor_id": "beacon-visitor-001",
            "events": [
                {
                    "type": "pageview",
                    "url": "https://test-ingest.example.com/pricing",
                    "ts": "2026-05-27T00:00:00",
                }
            ],
        }
        resp = await test_client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={"Content-Type": "text/plain"},
        )
        assert resp.status_code == 204


class TestEmailCaptureSource:
    """P4: a captured email is stored with the pixel-provided source label so we
    can tell a newsletter signup from a checkout from a login."""

    @staticmethod
    def _patch_validate(monkeypatch):
        async def _ok(_email):
            return (True, "")
        monkeypatch.setattr("apps.api.services.email_validator.validate_email", _ok)

    @pytest.mark.asyncio
    async def test_source_label_stored(self, test_client, test_site_id, test_db, monkeypatch):
        from apps.api.models.visitor_email import VisitorEmail

        self._patch_validate(monkeypatch)
        resp = await test_client.post(
            "/api/v1/events/ingest",
            json={
                "site_id": test_site_id,
                "visitor_id": "cap-src-001",
                "events": [{
                    "type": "form_email_capture",
                    "email": "Buyer@Shop.com",
                    "source": "newsletter",
                    "ts": "2026-06-30T00:00:00",
                }],
            },
            headers={"User-Agent": _BROWSER_UA},
        )
        assert resp.status_code == 204, resp.text
        row = (
            await test_db.execute(
                select(VisitorEmail).where(VisitorEmail.visitor_id == "cap-src-001")
            )
        ).scalar_one()
        assert row.email == "buyer@shop.com"  # normalized to lowercase
        assert row.source == "newsletter"

    @pytest.mark.asyncio
    async def test_source_defaults_to_form(self, test_client, test_site_id, test_db, monkeypatch):
        from apps.api.models.visitor_email import VisitorEmail

        self._patch_validate(monkeypatch)
        resp = await test_client.post(
            "/api/v1/events/ingest",
            json={
                "site_id": test_site_id,
                "visitor_id": "cap-src-002",
                "events": [{
                    "type": "form_email_capture",
                    "email": "x@shop.com",
                    "ts": "2026-06-30T00:00:00",
                }],
            },
            headers={"User-Agent": _BROWSER_UA},
        )
        assert resp.status_code == 204, resp.text
        row = (
            await test_db.execute(
                select(VisitorEmail).where(VisitorEmail.visitor_id == "cap-src-002")
            )
        ).scalar_one()
        assert row.source == "form"


class TestAgentDetection:
    """EvalLayer Phase 2 — classify-then-branch agent-visit persistence.

    All cases require MOCK_EXTERNAL_APIS=true. AC1/AC2/AC4 monkeypatch
    settings.agent_detection_enabled=True on the imported singleton (events.py
    binds the same instance via `from apps.api.config import settings`).
    """

    _GPTBOT_UA = "Mozilla/5.0 (compatible; GPTBot/1.0; +https://openai.com/gptbot)"

    @staticmethod
    def _enable(monkeypatch, value=True):
        from apps.api.config import settings
        monkeypatch.setattr(settings, "agent_detection_enabled", value)

    @pytest.mark.asyncio
    async def test_ac1_gptbot_persists_agent_visit(self, test_client, test_site_id, test_db, monkeypatch):
        """AC1: GPTBot UA + flag ON → one agent_visits row (vendor=openai) + 204."""
        from apps.api.models.agent_visit import AgentVisit

        self._enable(monkeypatch)
        payload = {
            "site_id": test_site_id,
            "visitor_id": "agent-visitor-ac1",
            "events": [{
                "type": "pageview",
                "url": "https://test-ingest.example.com/pricing",
                "page_path": "/pricing",
                "ts": "2026-05-27T00:00:00",
            }],
        }
        resp = await test_client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={"Content-Type": "application/json", "User-Agent": self._GPTBOT_UA},
        )
        assert resp.status_code == 204, resp.text
        rows = (
            await test_db.execute(
                select(AgentVisit).where(AgentVisit.site_id == test_site_id)
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].vendor == "openai"
        assert rows[0].product_or_ua_token == "gptbot"
        assert rows[0].verification_method == "ua-only"
        assert rows[0].visit_count == 1
        assert rows[0].page_paths == ["/pricing"]

    @pytest.mark.asyncio
    async def test_ac2_agent_batch_creates_no_human_rows(self, test_client, test_site_id, test_db, monkeypatch):
        """AC2: agent-only batch → zero new Visitor/Event rows for the site."""
        from apps.api.models.event import Event
        from apps.api.models.visitor import Visitor

        self._enable(monkeypatch)

        async def _count(model):
            return len((
                await test_db.execute(select(model).where(model.site_id == test_site_id))
            ).scalars().all())

        events_before = await _count(Event)
        visitors_before = await _count(Visitor)

        payload = {
            "site_id": test_site_id,
            "visitor_id": "agent-visitor-ac2",
            "events": [{
                "type": "pageview",
                "url": "https://test-ingest.example.com/",
                "page_path": "/",
                "ts": "2026-05-27T00:00:00",
            }],
        }
        resp = await test_client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={"Content-Type": "application/json", "User-Agent": self._GPTBOT_UA},
        )
        assert resp.status_code == 204, resp.text
        assert await _count(Event) == events_before
        assert await _count(Visitor) == visitors_before

    @pytest.mark.asyncio
    async def test_ac3_googlebot_creates_no_agent_visit(self, test_client, test_site_id, test_db, monkeypatch):
        """AC3: Googlebot → 204-dropped, NO agent_visits row (even with flag ON)."""
        from apps.api.models.agent_visit import AgentVisit

        self._enable(monkeypatch)
        payload = {
            "site_id": test_site_id,
            "visitor_id": "googlebot-visitor",
            "events": [{
                "type": "pageview",
                "url": "https://test-ingest.example.com/",
                "page_path": "/",
                "ts": "2026-05-27T00:00:00",
            }],
        }
        resp = await test_client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Googlebot/2.1 (+http://www.google.com/bot.html)",
            },
        )
        assert resp.status_code == 204, resp.text
        rows = (
            await test_db.execute(
                select(AgentVisit).where(AgentVisit.vendor == "googlebot")
            )
        ).scalars().all()
        assert rows == []

    @pytest.mark.asyncio
    async def test_ac4_datacenter_flagged_ip_still_persists(self, test_client, test_site_id, test_db, monkeypatch):
        """AC4: GPTBot + datacenter-flagged IP → visit still persists.

        The agent branch hard-returns BEFORE the datacenter check, so the
        monkeypatched is_datacenter_ip=True is never consulted for this request.
        """
        from apps.api.models.agent_visit import AgentVisit

        self._enable(monkeypatch)

        async def _always_datacenter(_ip):
            return True

        monkeypatch.setattr(
            "apps.api.services.company_resolver.is_datacenter_ip", _always_datacenter
        )

        payload = {
            "site_id": test_site_id,
            "visitor_id": "agent-visitor-ac4",
            "events": [{
                "type": "pageview",
                "url": "https://test-ingest.example.com/docs",
                "page_path": "/docs",
                "ts": "2026-05-27T00:00:00",
            }],
        }
        resp = await test_client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={
                "Content-Type": "application/json",
                "User-Agent": self._GPTBOT_UA,
                "X-Forwarded-For": "203.0.113.7",
            },
        )
        assert resp.status_code == 204, resp.text
        rows = (
            await test_db.execute(
                select(AgentVisit).where(
                    AgentVisit.site_id == test_site_id,
                    AgentVisit.product_or_ua_token == "gptbot",
                )
            )
        ).scalars().all()
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_flag_off_gptbot_dropped_no_agent_visit(self, test_client, test_site_id, test_db):
        """flag-OFF (default): GPTBot dropped via is_bot(), 0 agent_visits rows."""
        from apps.api.models.agent_visit import AgentVisit

        # Do NOT enable the flag — exercise byte-identical pre-Phase-2 behavior.
        payload = {
            "site_id": test_site_id,
            "visitor_id": "agent-visitor-off",
            "events": [{
                "type": "pageview",
                "url": "https://test-ingest.example.com/",
                "page_path": "/",
                "ts": "2026-05-27T00:00:00",
            }],
        }
        resp = await test_client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={"Content-Type": "application/json", "User-Agent": self._GPTBOT_UA},
        )
        assert resp.status_code == 204, resp.text
        rows = (
            await test_db.execute(
                select(AgentVisit).where(AgentVisit.product_or_ua_token == "gptbot")
            )
        ).scalars().all()
        assert rows == []


class TestCookieFpPhase2:
    """First-party cookie + fingerprint hardening (cook Phase 2)."""

    @pytest.mark.asyncio
    async def test_ingest_cors_echoes_origin_with_credentials(self, test_client, test_site_id):
        """Credentialed cross-origin ingest must not use ACAO=*."""
        origin = "https://lab.example.com"
        payload = {
            "site_id": test_site_id,
            "visitor_id": "cors-cred-visitor",
            "events": [{
                "type": "pageview",
                "url": "https://lab.example.com/",
                "page_path": "/",
                "ts": "2026-05-27T00:00:00",
            }],
        }
        resp = await test_client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={
                "Content-Type": "text/plain",
                "User-Agent": _BROWSER_UA,
                "Origin": origin,
            },
        )
        assert resp.status_code == 204, resp.text
        assert resp.headers.get("access-control-allow-origin") == origin
        assert resp.headers.get("access-control-allow-credentials") == "true"

    @pytest.mark.asyncio
    async def test_ingest_options_preflight_credentialed(self, test_client, test_site_id):
        origin = "https://lab.example.com"
        resp = await test_client.options(
            "/api/v1/events/ingest",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == origin
        assert resp.headers.get("access-control-allow-credentials") == "true"

    @pytest.mark.asyncio
    async def test_fingerprint_persists_before_aggregation(
        self, test_client, test_site_id, test_db
    ):
        """_fp on first batch must stick even though aggregator runs later."""
        from apps.api.models.visitor import Visitor

        vid = "fp-oneshot-visitor"
        fp = "fp2_oneshotphase2testabc"
        payload = {
            "site_id": test_site_id,
            "visitor_id": vid,
            "events": [{
                "type": "pageview",
                "url": "https://test-ingest.example.com/",
                "page_path": "/",
                "ts": "2026-05-27T00:00:00",
                "_fp": fp,
            }],
        }
        resp = await test_client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={"Content-Type": "text/plain", "User-Agent": _BROWSER_UA},
        )
        assert resp.status_code == 204, resp.text

        row = (
            await test_db.execute(
                select(Visitor).where(
                    Visitor.site_id == test_site_id,
                    Visitor.visitor_id == vid,
                )
            )
        ).scalar_one_or_none()
        assert row is not None, "visitor stub must exist immediately after ingest"
        assert row.fingerprint == fp

    @pytest.mark.asyncio
    async def test_svid_cookie_stamps_server_visitor_id(
        self, test_client, test_site_id, test_db
    ):
        """Returning wiped client id + _rta_svid cookie → server_visitor_id."""
        from apps.api.models.visitor import Visitor

        site_id = test_site_id
        cookie_name = "_rta_svid_" + "".join(c for c in site_id if c.isalnum() or c == "_")
        original = "orig-visitor-root-001"
        wiped = "wiped-client-visitor-002"
        payload = {
            "site_id": site_id,
            "visitor_id": wiped,
            "events": [{
                "type": "pageview",
                "url": "https://test-ingest.example.com/",
                "page_path": "/",
                "ts": "2026-05-27T00:00:00",
                "_fp": "fp2_wipedreturnabc123",
            }],
        }
        resp = await test_client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={
                "Content-Type": "text/plain",
                "User-Agent": _BROWSER_UA,
                "Cookie": f"{cookie_name}={original}",
            },
        )
        assert resp.status_code == 204, resp.text

        row = (
            await test_db.execute(
                select(Visitor).where(
                    Visitor.site_id == site_id,
                    Visitor.visitor_id == wiped,
                )
            )
        ).scalar_one_or_none()
        assert row is not None
        assert row.server_visitor_id == original

    @pytest.mark.asyncio
    async def test_deleted_site_403_cors_allows_credentialed_cookie_clear(
        self, test_client
    ):
        """Cross-origin 403 must echo Origin+credentials so pixel can apply
        Set-Cookie expiry for HttpOnly _rta_svid (selfDestruct path)."""
        origin = "https://lab.example.com"
        site_id = "nonexistent_site_cors_403"
        payload = {
            "site_id": site_id,
            "visitor_id": "test-visitor",
            "events": [{
                "type": "pageview",
                "url": "https://lab.example.com/",
                "ts": "2026-05-27T00:00:00",
            }],
        }
        resp = await test_client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={
                "Content-Type": "text/plain",
                "User-Agent": _BROWSER_UA,
                "Origin": origin,
            },
        )
        assert resp.status_code == 403
        assert resp.headers.get("access-control-allow-origin") == origin
        assert resp.headers.get("access-control-allow-credentials") == "true"
        set_cookies = resp.headers.get_list("set-cookie")
        assert any("_rta_svid_nonexistent_site_cors_403" in c for c in set_cookies)

    @pytest.mark.asyncio
    async def test_fingerprint_survives_aggregation_totals(
        self, test_client, test_site_id, test_db
    ):
        """AC#5: after aggregate, pageviews filled and FP/svid untouched."""
        from apps.api.models.visitor import Visitor
        from apps.api.services.visitor_aggregator import aggregate_visitors_for_site

        vid = "fp-agg-survive-visitor"
        fp = "fp2_aggsurvivephase2xyz"
        cookie_name = "_rta_svid_" + "".join(
            c for c in test_site_id if c.isalnum() or c == "_"
        )
        original = "root-before-wipe-agg"
        payload = {
            "site_id": test_site_id,
            "visitor_id": vid,
            "events": [{
                "type": "pageview",
                "url": "https://test-ingest.example.com/pricing",
                "page_path": "/pricing",
                "ts": "2026-05-27T00:00:00",
                "_fp": fp,
            }],
        }
        resp = await test_client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={
                "Content-Type": "text/plain",
                "User-Agent": _BROWSER_UA,
                "Cookie": f"{cookie_name}={original}",
            },
        )
        assert resp.status_code == 204, resp.text

        await aggregate_visitors_for_site(test_db, test_site_id, since=None)
        await test_db.commit()

        row = (
            await test_db.execute(
                select(Visitor).where(
                    Visitor.site_id == test_site_id,
                    Visitor.visitor_id == vid,
                )
            )
        ).scalar_one_or_none()
        assert row is not None
        assert row.fingerprint == fp
        assert row.server_visitor_id == original
        assert row.total_pageviews >= 1


class TestUnknownSiteObservability:
    """AC2 — the unknown-site 403 emits a structured, aggregatable log event.

    AC9 (byte-identical response) is covered by the untouched
    test_invalid_site_returns_403 / test_deleted_site_403_expires_svid_cookie
    cases above; this class only adds observability cover.
    """

    @pytest.mark.asyncio
    async def test_unknown_site_logs_structured_event(
        self, test_client, test_site_id, monkeypatch
    ):
        from apps.api.routers import events as events_router

        captured: list[tuple[str, dict]] = []
        real_warning = events_router.logger.warning

        def _capture(event: str, **kw):
            captured.append((event, kw))
            return real_warning(event, **kw)

        monkeypatch.setattr(events_router.logger, "warning", _capture)

        orphan_id = "orphaned_site_ac2_test"
        payload = {
            "site_id": orphan_id,
            "visitor_id": "test-visitor",
            "events": [
                {
                    "type": "pageview",
                    "url": "https://example.com/",
                    "ts": "2026-05-27T00:00:00",
                }
            ],
        }
        resp = await test_client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA},
        )

        # Response contract unchanged (AC9).
        assert resp.status_code == 403
        assert resp.content == b""

        matching = [kw for name, kw in captured if name == "ingest_unknown_site"]
        assert matching, f"no ingest_unknown_site event captured: {captured}"
        assert matching[0]["site_id"] == orphan_id
        assert matching[0]["rejected_as"] == "unknown_site"

    @pytest.mark.asyncio
    async def test_counter_failure_does_not_break_the_403(
        self, test_client, test_site_id, monkeypatch
    ):
        """Fail-open: a raising counter must not turn the 403 into a 500."""
        from apps.api.routers import events as events_router
        from apps.api.services import orphan_ingest_metrics as oim

        class _BoomRedis:
            async def incr(self, key):
                raise RuntimeError("redis down")

            async def expire(self, key, seconds):
                raise RuntimeError("redis down")

        # Patch the redis accessor (not the helper) so the helper's own
        # fail-open try/except is what is actually exercised here.
        monkeypatch.setattr(oim, "get_redis", lambda: _BoomRedis())
        assert events_router.record_orphan_ingest is oim.record_orphan_ingest

        payload = {
            "site_id": "orphaned_site_failopen",
            "visitor_id": "test-visitor",
            "events": [
                {
                    "type": "pageview",
                    "url": "https://example.com/",
                    "ts": "2026-05-27T00:00:00",
                }
            ],
        }
        resp = await test_client.post(
            "/api/v1/events/ingest",
            content=json.dumps(payload),
            headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA},
        )
        assert resp.status_code == 403
        assert resp.content == b""
