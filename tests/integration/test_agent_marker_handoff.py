"""Integration tests for the F2 marker click path (agent → human handoff).

The unit tests cover mint/decode/stamp and the write helper in isolation. What
only a live ingest can prove is the WIRING: that an ordinary pageview carrying
``_bam`` — no special event type, no tracker change — actually reaches
``record_marker_handoff`` and produces a deterministic ``agent_handoff_links``
row, and that the temporal sweep's guess is superseded rather than kept.

Requires: PostgreSQL + Redis running locally (via docker-compose).
Uses test_client and test_db from conftest.py which auto-create tables.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from apps.api.config import settings
from apps.api.models.agent_fetch_event import AgentFetchEvent
from apps.api.models.agent_handoff_link import AgentHandoffLink
from apps.api.services.agent_marker import MARKER_PARAM, mint_marker

_BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def marker_site(test_db):
    from apps.api.models.site import Site
    from apps.api.models.user import User

    result = await test_db.execute(select(User).where(User.email == "test-marker@test.com"))
    user = result.scalar_one_or_none()
    if not user:
        user = User(email="test-marker@test.com", full_name="Marker User")
        test_db.add(user)
        await test_db.flush()

    site_id = "test_site_marker"
    result = await test_db.execute(select(Site).where(Site.site_id == site_id))
    if not result.scalar_one_or_none():
        test_db.add(
            Site(
                site_id=site_id,
                user_id=user.id,
                name="Marker Site",
                url="https://test-marker.example.com",
            )
        )
        await test_db.flush()
    await test_db.commit()
    return site_id


@pytest_asyncio.fixture
async def agent_fetch(test_db, marker_site):
    """A recorded agent fetch — what a marker names."""
    row = AgentFetchEvent(
        site_id=marker_site,
        vendor="openai",
        raw_ua_token="chatgpt-user",
        tier="on-demand",
        page_path="/pricing",
        verification_method="ua-only",
    )
    test_db.add(row)
    await test_db.commit()
    await test_db.refresh(row)
    return row


@pytest_asyncio.fixture
def marker_enabled(monkeypatch):
    from cryptography.fernet import Fernet
    from apps.api.services import link_decorator

    monkeypatch.setattr(settings, "agent_marker_enabled", True)
    if not link_decorator.settings.encryption_key:
        monkeypatch.setattr(
            link_decorator.settings, "encryption_key", Fernet.generate_key().decode()
        )


def _pageview(site_id, visitor_id, url):
    return {
        "site_id": site_id,
        "visitor_id": visitor_id,
        "events": [
            {
                "type": "pageview",
                "url": url,
                "page_path": "/pricing",
                "page_title": "Pricing",
                "user_agent": _BROWSER_UA,
                "ts": "2026-07-29T00:00:00",
            }
        ],
    }


class TestMarkerClickWiring:
    @pytest.mark.asyncio
    async def test_plain_pageview_with_marker_creates_the_link(
        self, test_client, test_db, marker_site, agent_fetch, marker_enabled
    ):
        """The load-bearing wiring claim: a normal pageview is enough. No new
        event type, no pixel change."""
        token = mint_marker(agent_fetch.id)
        url = f"https://test-marker.example.com/pricing?{MARKER_PARAM}={token}"

        resp = await test_client.post(
            "/api/v1/events/ingest",
            json=_pageview(marker_site, "marker-visitor-1", url),
            headers={"User-Agent": _BROWSER_UA},
        )
        assert resp.status_code == 204

        link = (
            await test_db.execute(
                select(AgentHandoffLink).where(
                    AgentHandoffLink.agent_fetch_event_id == agent_fetch.id
                )
            )
        ).scalar_one_or_none()
        assert link is not None
        assert link.visitor_id == "marker-visitor-1"
        assert link.method == "marker"
        assert link.confidence == "high"
        assert link.site_id == marker_site

    @pytest.mark.asyncio
    async def test_marker_supersedes_a_temporal_guess(
        self, test_client, test_db, marker_site, agent_fetch, marker_enabled
    ):
        """The sweep may already have guessed a visitor for this fetch. The marker
        is the ground truth that guess was approximating, so it must win."""
        test_db.add(
            AgentHandoffLink(
                site_id=marker_site,
                visitor_id="guessed-visitor",
                agent_fetch_event_id=agent_fetch.id,
                confidence="medium",
                method="temporal-page-match",
                delta_seconds=900,
                matched_page="/pricing",
            )
        )
        await test_db.commit()

        token = mint_marker(agent_fetch.id)
        resp = await test_client.post(
            "/api/v1/events/ingest",
            json=_pageview(
                marker_site,
                "real-visitor",
                f"https://test-marker.example.com/pricing?{MARKER_PARAM}={token}",
            ),
            headers={"User-Agent": _BROWSER_UA},
        )
        assert resp.status_code == 204

        links = (
            await test_db.execute(
                select(AgentHandoffLink).where(
                    AgentHandoffLink.agent_fetch_event_id == agent_fetch.id
                )
            )
        ).scalars().all()
        # Still exactly one link — the fetch's unique constraint holds.
        assert len(links) == 1
        assert links[0].method == "marker"
        assert links[0].visitor_id == "real-visitor"

    @pytest.mark.asyncio
    async def test_second_click_does_not_reattribute_the_fetch(
        self, test_client, test_db, marker_site, agent_fetch, marker_enabled
    ):
        """A shared or forwarded link must not move the attribution to whoever
        clicked last — first real click wins."""
        token = mint_marker(agent_fetch.id)
        url = f"https://test-marker.example.com/pricing?{MARKER_PARAM}={token}"

        for visitor in ("first-clicker", "second-clicker"):
            resp = await test_client.post(
                "/api/v1/events/ingest",
                json=_pageview(marker_site, visitor, url),
                headers={"User-Agent": _BROWSER_UA},
            )
            assert resp.status_code == 204

        links = (
            await test_db.execute(
                select(AgentHandoffLink).where(
                    AgentHandoffLink.agent_fetch_event_id == agent_fetch.id
                )
            )
        ).scalars().all()
        assert len(links) == 1
        assert links[0].visitor_id == "first-clicker"

    @pytest.mark.asyncio
    async def test_forged_marker_creates_nothing(
        self, test_client, test_db, marker_site, marker_enabled
    ):
        resp = await test_client.post(
            "/api/v1/events/ingest",
            json=_pageview(
                marker_site,
                "forger",
                f"https://test-marker.example.com/pricing?{MARKER_PARAM}=not-a-token",
            ),
            headers={"User-Agent": _BROWSER_UA},
        )
        assert resp.status_code == 204

        count = (
            await test_db.execute(
                select(AgentHandoffLink).where(AgentHandoffLink.site_id == marker_site)
            )
        ).scalars().all()
        assert count == []

    @pytest.mark.asyncio
    async def test_marker_from_another_site_does_not_cross_tenants(
        self, test_client, test_db, marker_site, agent_fetch, marker_enabled
    ):
        """A marker minted for one site, replayed at another, must not link."""
        from apps.api.models.site import Site
        from apps.api.models.user import User

        user = (
            await test_db.execute(select(User).where(User.email == "test-marker@test.com"))
        ).scalar_one()
        other_id = "test_site_marker_other"
        if not (
            await test_db.execute(select(Site).where(Site.site_id == other_id))
        ).scalar_one_or_none():
            test_db.add(
                Site(
                    site_id=other_id,
                    user_id=user.id,
                    name="Other",
                    url="https://other-marker.example.com",
                )
            )
            await test_db.commit()

        token = mint_marker(agent_fetch.id)
        resp = await test_client.post(
            "/api/v1/events/ingest",
            json=_pageview(
                other_id,
                "cross-tenant-visitor",
                f"https://other-marker.example.com/pricing?{MARKER_PARAM}={token}",
            ),
            headers={"User-Agent": _BROWSER_UA},
        )
        assert resp.status_code == 204

        # The link, if any, must never be filed under the OTHER site.
        wrong = (
            await test_db.execute(
                select(AgentHandoffLink).where(AgentHandoffLink.site_id == other_id)
            )
        ).scalars().all()
        assert wrong == [] or all(
            link.agent_fetch_event_id != agent_fetch.id for link in wrong
        )

    @pytest.mark.asyncio
    async def test_flag_off_writes_no_link(
        self, test_client, test_db, marker_site, agent_fetch, monkeypatch
    ):
        monkeypatch.setattr(settings, "agent_marker_enabled", False)
        token = mint_marker(agent_fetch.id) or "x"
        resp = await test_client.post(
            "/api/v1/events/ingest",
            json=_pageview(
                marker_site,
                "flag-off-visitor",
                f"https://test-marker.example.com/pricing?{MARKER_PARAM}={token}",
            ),
            headers={"User-Agent": _BROWSER_UA},
        )
        assert resp.status_code == 204

        link = (
            await test_db.execute(
                select(AgentHandoffLink).where(
                    AgentHandoffLink.agent_fetch_event_id == agent_fetch.id
                )
            )
        ).scalar_one_or_none()
        assert link is None
