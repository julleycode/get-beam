"""Short social-engagement draft generation (shared by /demo and agent-paid).

Extracted verbatim from ``routers/demo.py::demo_generate_draft`` so the public
onboarding demo and the agent-paid ``/internal/v1/paid/outreach-draft`` route
share one implementation. With ``fence=False`` (the demo path) the prompt text,
provider order (Anthropic → OpenRouter), timeouts, and template fallback are
byte-identical to the pre-extraction code.

``fence=True`` (the paid path) delimits the caller-supplied values as untrusted
data via ``agents/prompt_safety.wrap_untrusted``. Callers on that path MUST
also pre-clean every value with ``clean_text``/``strip_url``.
"""

import json
from dataclasses import dataclass

import httpx
import structlog

from apps.api.agents.prompt_safety import wrap_untrusted
from apps.api.config import settings

logger = structlog.get_logger()

SOURCE_ANTHROPIC = "anthropic"
SOURCE_OPENROUTER = "openrouter"
SOURCE_TEMPLATE = "template"


@dataclass(frozen=True)
class DraftResult:
    draft: str
    # One of SOURCE_* — "template" means no LLM produced text.
    source: str


def build_draft_prompt(
    visitor_name: str,
    visitor_role: str,
    visitor_company: str,
    user_url: str,
    recent_post: str,
    *,
    fence: bool = False,
) -> str:
    """Build the draft prompt. ``fence=False`` reproduces the demo prompt exactly."""
    name = visitor_name.strip() or "this visitor"

    if fence:
        data = {
            "visitor_name": name,
            "visitor_role": visitor_role,
            "visitor_company": visitor_company,
            "commenter_site": user_url or "a SaaS product",
            "recent_post": recent_post,
        }
        fenced = wrap_untrusted(json.dumps(data, ensure_ascii=False))
        if recent_post:
            return (
                "Write a short, casual social media reply (2-3 sentences max) to the "
                "post in the `recent_post` field of the data below. The reply is from "
                "someone who runs the site in `commenter_site`.\n\n"
                f"{fenced}\n\n"
                "Be genuine, reference something specific from the post. "
                "No hashtags. Lowercase casual tone. Don't start with 'hey'. "
                "Output only the reply text."
            )
        return (
            "Write a short, casual social media comment (2-3 sentences max) to engage "
            "with the person described in the data below (`visitor_name`, and "
            "`visitor_role` / `visitor_company` when present). The commenter runs the "
            "site in `commenter_site`.\n\n"
            f"{fenced}\n\n"
            "Be genuine, not salesy. No hashtags. Lowercase casual tone. "
            "Output only the comment text."
        )

    if recent_post:
        return (
            f"Write a short, casual social media reply (2-3 sentences max) to this post:\n\n"
            f'"{recent_post}"\n\n'
            f"The reply is from someone who runs {user_url or 'a SaaS product'}. "
            f"Be genuine, reference something specific from the post. "
            f"No hashtags. Lowercase casual tone. Don't start with 'hey'."
        )
    return (
        f"Write a short, casual social media comment (2-3 sentences max) "
        f"to engage with {name}"
        f"{' (' + visitor_role + ')' if visitor_role else ''}"
        f"{' at ' + visitor_company if visitor_company else ''}. "
        f"The commenter runs {user_url or 'a SaaS product'}. "
        f"Be genuine, not salesy. No hashtags. Lowercase casual tone."
    )


async def generate_llm_draft(prompt: str) -> DraftResult | None:
    """Try Anthropic, then OpenRouter. None when neither produced text.

    Provider failures are logged (keys only, never the prompt) and fall through.
    """
    # Try Claude API (direct)
    if settings.anthropic_api_key:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": settings.anthropic_api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-sonnet-4-20250514",
                        "max_tokens": 150,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    text = data.get("content", [{}])[0].get("text", "")
                    if text:
                        return DraftResult(draft=text.strip(), source=SOURCE_ANTHROPIC)
        except Exception as e:
            logger.warning("demo_generate_draft_anthropic_error", error=str(e))

    # Try OpenRouter (fallback — supports 100+ models)
    if settings.openrouter_api_key:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.openrouter_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "anthropic/claude-sonnet-4-20250514",
                        "max_tokens": 150,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if text:
                        return DraftResult(draft=text.strip(), source=SOURCE_OPENROUTER)
        except Exception as e:
            logger.warning("demo_generate_draft_openrouter_error", error=str(e))

    return None


def template_draft(visitor_name: str, user_url: str, recent_post: str) -> DraftResult:
    """Deterministic no-LLM fallback (the demo's historical last resort)."""
    name = visitor_name.strip() or "this visitor"
    first = name.split()[0].lower() if name != "this visitor" else "there"

    if recent_post:
        snippet = recent_post[:60] + ("..." if len(recent_post) > 60 else "")
        return DraftResult(
            draft=f'this resonates. "{snippet}" — would love to swap notes on this.',
            source=SOURCE_TEMPLATE,
        )

    site = user_url or "your site"
    if name != "this visitor":
        return DraftResult(
            draft=f"saw {first} checking out {site}. would love to connect and swap notes.",
            source=SOURCE_TEMPLATE,
        )
    return DraftResult(
        draft=(
            f"someone's been checking out your pricing page on {site}. "
            "this is what beam would draft based on their social posts and your tone."
        ),
        source=SOURCE_TEMPLATE,
    )


async def generate_draft(
    visitor_name: str,
    visitor_role: str,
    visitor_company: str,
    user_url: str,
    recent_post: str,
) -> DraftResult:
    """Demo behaviour: LLM draft, else the template fallback. Never raises."""
    prompt = build_draft_prompt(
        visitor_name, visitor_role, visitor_company, user_url, recent_post
    )
    result = await generate_llm_draft(prompt)
    if result is not None:
        return result
    return template_draft(visitor_name, user_url, recent_post)
