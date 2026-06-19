"""Integration test for the AI assistant endpoint.

POST /api/v1/ai/ask answers a free-text question about the caller's OWN Beam
workspace via Gemini. Gemini is mocked here so the test is hermetic (no key,
no network). Context-scoping (one tenant can't read another's site) is the
security-critical assertion.

Requires: PostgreSQL running locally (via docker-compose).
"""

import uuid as uuidlib

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration


async def _signup(test_client, email: str) -> str:
    resp = await test_client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "testpass123", "full_name": "AI Tester"},
    )
    if resp.status_code != 200:
        resp = await test_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "testpass123"}
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def ai_setup(test_client, test_db):
    from apps.api.models.site import Site
    from apps.api.models.user import User

    email = f"ai-{uuidlib.uuid4().hex[:8]}@test.com"
    token = await _signup(test_client, email)
    user = (
        await test_db.execute(select(User).where(User.email == email))
    ).scalar_one()

    site_id = f"ai_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(
        Site(site_id=site_id, user_id=user.id, name="AI Site", url="https://ai.example.com")
    )
    await test_db.commit()
    return {"token": token, "site_id": site_id, "email": email}


class TestAiAsk:
    @pytest.mark.asyncio
    async def test_answer_returned(self, test_client, ai_setup, monkeypatch):
        async def fake_generate(prompt, **kwargs):
            # The caller's workspace snapshot must be injected into the prompt.
            assert "WORKSPACE DATA" in prompt
            return "Install the pixel, then identify high-intent visitors."

        monkeypatch.setattr("apps.api.routers.ai.gemini_generate", fake_generate)

        resp = await test_client.post(
            "/api/v1/ai/ask",
            json={"question": "What should I do first?", "site_id": ai_setup["site_id"]},
            headers=_auth(ai_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        assert "pixel" in resp.json()["answer"].lower()

    @pytest.mark.asyncio
    async def test_works_without_site_id(self, test_client, ai_setup, monkeypatch):
        async def fake_generate(prompt, **kwargs):
            return "You have one site — check the Visitors page."

        monkeypatch.setattr("apps.api.routers.ai.gemini_generate", fake_generate)

        resp = await test_client.post(
            "/api/v1/ai/ask",
            json={"question": "Summarize my workspace"},
            headers=_auth(ai_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["answer"]

    @pytest.mark.asyncio
    async def test_requires_auth(self, test_client):
        resp = await test_client.post("/api/v1/ai/ask", json={"question": "hi"})
        assert resp.status_code == 401, resp.text

    @pytest.mark.asyncio
    async def test_other_users_site_is_404(self, test_client, ai_setup):
        # A different user must not point the question at someone else's site —
        # the ownership check 404s before any context is built or Gemini called.
        other = await _signup(test_client, f"other-{uuidlib.uuid4().hex[:8]}@test.com")
        resp = await test_client.post(
            "/api/v1/ai/ask",
            json={"question": "spy on them", "site_id": ai_setup["site_id"]},
            headers=_auth(other),
        )
        assert resp.status_code == 404, resp.text

    @pytest.mark.asyncio
    async def test_gemini_failure_returns_503(self, test_client, ai_setup, monkeypatch):
        from apps.api.services.gemini_client import GeminiError

        async def boom(prompt, **kwargs):
            raise GeminiError("quota exceeded")

        monkeypatch.setattr("apps.api.routers.ai.gemini_generate", boom)

        resp = await test_client.post(
            "/api/v1/ai/ask",
            json={"question": "anything", "site_id": ai_setup["site_id"]},
            headers=_auth(ai_setup["token"]),
        )
        assert resp.status_code == 503, resp.text

    @pytest.mark.asyncio
    async def test_question_required(self, test_client, ai_setup):
        # Empty question fails Pydantic validation (min_length=1) → 422.
        resp = await test_client.post(
            "/api/v1/ai/ask",
            json={"question": ""},
            headers=_auth(ai_setup["token"]),
        )
        assert resp.status_code == 422, resp.text
