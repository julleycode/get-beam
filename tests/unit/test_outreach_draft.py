"""Regression tests for the /demo/generate-draft extraction (services/outreach_draft.py).

The demo path (fence=False) must stay byte-identical to the pre-extraction
inline code in routers/demo.py: same prompt text, same template fallback.
"""

from unittest.mock import AsyncMock

import pytest

from apps.api.config import settings
from apps.api.services import outreach_draft as od


def _legacy_prompt(name_in: str, role: str, company: str, url: str, post: str) -> str:
    """Verbatim copy of the pre-extraction demo prompt builder."""
    name = name_in.strip() or "this visitor"
    if post:
        return (
            f"Write a short, casual social media reply (2-3 sentences max) to this post:\n\n"
            f'"{post}"\n\n'
            f"The reply is from someone who runs {url or 'a SaaS product'}. "
            f"Be genuine, reference something specific from the post. "
            f"No hashtags. Lowercase casual tone. Don't start with 'hey'."
        )
    return (
        f"Write a short, casual social media comment (2-3 sentences max) "
        f"to engage with {name}"
        f"{' (' + role + ')' if role else ''}"
        f"{' at ' + company if company else ''}. "
        f"The commenter runs {url or 'a SaaS product'}. "
        f"Be genuine, not salesy. No hashtags. Lowercase casual tone."
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "args",
    [
        ("Jane Doe", "CTO", "Acme", "acme.io", ""),
        ("", "", "", "", ""),
        ("Jane", "", "Acme", "", "shipping v2 today"),
        ("  ", "CTO", "", "x.com", ""),
    ],
)
def test_demo_prompt_is_unchanged(args):
    assert od.build_draft_prompt(*args) == _legacy_prompt(*args)


@pytest.mark.unit
async def test_demo_template_fallback_unchanged(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    r = await od.generate_draft("Jane Doe", "", "", "acme.io", "")
    assert r.draft == "saw jane checking out acme.io. would love to connect and swap notes."
    assert r.source == od.SOURCE_TEMPLATE
    r = await od.generate_draft("", "", "", "", "")
    assert r.draft == (
        "someone's been checking out your pricing page on your site. "
        "this is what beam would draft based on their social posts and your tone."
    )
    post = "x" * 70
    r = await od.generate_draft("", "", "", "", post)
    assert r.draft == f'this resonates. "{"x" * 60}..." — would love to swap notes on this.'


@pytest.mark.unit
async def test_demo_router_returns_llm_draft(monkeypatch):
    from apps.api.routers import demo

    monkeypatch.setattr(demo, "_enforce_demo_budget", AsyncMock())
    monkeypatch.setattr(
        od, "generate_llm_draft", AsyncMock(return_value=od.DraftResult("hi there", "anthropic"))
    )
    body = demo.DraftRequest(visitor_name="Jane")
    # Call the undecorated coroutine (slowapi wrapper needs a real Request).
    result = await demo.demo_generate_draft.__wrapped__(request=None, body=body)  # type: ignore[attr-defined]
    assert result == {"draft": "hi there"}
