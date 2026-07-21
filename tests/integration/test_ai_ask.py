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


def _script_loop(monkeypatch, responses: list[dict]) -> list[dict]:
    """Patch the Gemini transport seam with scripted responses; capture deep
    copies of each request body so tests can inspect the functionResponse the
    loop actually built (i.e. prove the tool handlers hit the test DB)."""
    import json as jsonlib

    from apps.api.services import gemini_client

    bodies: list[dict] = []

    async def fake_post(body, model, *, client=None):
        bodies.append(jsonlib.loads(jsonlib.dumps(body)))
        return responses[min(len(bodies) - 1, len(responses) - 1)]

    monkeypatch.setattr(gemini_client, "_post_generate", fake_post)
    return bodies


def _call_stats(site_id: str) -> dict:
    return {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {
                            "functionCall": {
                                "name": "get_site_stats",
                                "args": {"site_id": site_id},
                            }
                        }
                    ],
                }
            }
        ],
        "usageMetadata": {"totalTokenCount": 10},
    }


def _text(answer: str) -> dict:
    return {
        "candidates": [{"content": {"role": "model", "parts": [{"text": answer}]}}],
        "usageMetadata": {"totalTokenCount": 10},
    }


class TestAiAskAgentic:
    """The tool-loop path added by the light-agentic upgrade."""

    @pytest.mark.asyncio
    async def test_tool_call_reads_workspace_through_request_session(
        self, test_client, ai_setup, monkeypatch
    ):
        bodies = _script_loop(
            monkeypatch,
            [
                _call_stats(ai_setup["site_id"]),
                _text("You have 0 visitors so far — install the pixel first."),
            ],
        )

        resp = await test_client.post(
            "/api/v1/ai/ask",
            json={
                "question": "How many visitors do I have?",
                "site_id": ai_setup["site_id"],
            },
            headers=_auth(ai_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        assert "visitors" in resp.json()["answer"]

        # The seed context carries the site_id the model needs for tool calls.
        assert f"site_id={ai_setup['site_id']}" in bodies[0]["contents"][0]["parts"][0]["text"]
        # The handler really ran against the seeded test DB.
        fr = bodies[1]["contents"][2]["parts"][0]["functionResponse"]
        assert fr["name"] == "get_site_stats"
        assert '"total_visitors": 0' in fr["response"]["data"]
        assert '"segments": 0' in fr["response"]["data"]

    @pytest.mark.asyncio
    async def test_tool_cannot_read_another_tenants_site(
        self, test_client, ai_setup, monkeypatch
    ):
        # A DIFFERENT user asks; the model (maliciously or steered) requests
        # the first user's site_id — the tool must answer "site not found".
        other_token = await _signup(
            test_client, f"other-agent-{uuidlib.uuid4().hex[:8]}@test.com"
        )
        bodies = _script_loop(
            monkeypatch,
            [_call_stats(ai_setup["site_id"]), _text("I could not find that site.")],
        )

        resp = await test_client.post(
            "/api/v1/ai/ask",
            json={"question": "Show stats for that site"},
            headers=_auth(other_token),
        )
        assert resp.status_code == 200, resp.text
        fr = bodies[1]["contents"][2]["parts"][0]["functionResponse"]
        assert fr["response"]["data"] == '{"error": "site not found"}'

    @pytest.mark.asyncio
    async def test_loop_failure_falls_back_to_single_shot(
        self, test_client, ai_setup, monkeypatch
    ):
        from apps.api.services.gemini_client import GeminiError

        async def boom_loop(*args, **kwargs):
            raise GeminiError("loop down")

        async def fake_generate(prompt, **kwargs):
            assert "WORKSPACE DATA" in prompt
            return "Fallback answer."

        monkeypatch.setattr("apps.api.routers.ai.gemini_agent_loop", boom_loop)
        monkeypatch.setattr("apps.api.routers.ai.gemini_generate", fake_generate)

        resp = await test_client.post(
            "/api/v1/ai/ask",
            json={"question": "anything", "site_id": ai_setup["site_id"]},
            headers=_auth(ai_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["answer"] == "Fallback answer."

    @pytest.mark.asyncio
    async def test_flag_off_uses_legacy_path_only(
        self, test_client, ai_setup, monkeypatch
    ):
        from apps.api.config import settings

        monkeypatch.setattr(settings, "ai_ask_tools_enabled", False)
        called = {"loop": False}

        async def loop_marker(*args, **kwargs):
            called["loop"] = True
            return "agentic"

        async def fake_generate(prompt, **kwargs):
            return "Legacy."

        monkeypatch.setattr("apps.api.routers.ai.gemini_agent_loop", loop_marker)
        monkeypatch.setattr("apps.api.routers.ai.gemini_generate", fake_generate)

        resp = await test_client.post(
            "/api/v1/ai/ask",
            json={"question": "anything"},
            headers=_auth(ai_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["answer"] == "Legacy."
        assert called["loop"] is False

    @pytest.mark.asyncio
    async def test_mock_mode_answers_via_real_handlers(
        self, test_client, ai_setup, monkeypatch
    ):
        # MOCK_EXTERNAL_APIS exercises the loop keylessly: the first tool
        # (list_sites) runs for real against the request DB session.
        from apps.api.config import settings

        monkeypatch.setattr(settings, "mock_external_apis", True)

        resp = await test_client.post(
            "/api/v1/ai/ask",
            json={"question": "What is my workspace status?"},
            headers=_auth(ai_setup["token"]),
        )
        assert resp.status_code == 200, resp.text
        answer = resp.json()["answer"]
        assert answer.startswith("MOCK ANSWER")
        assert "list_sites" in answer
