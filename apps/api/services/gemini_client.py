"""Gemini API client (httpx REST) — replaces legacy Anthropic for AI features.

Two modes:
- Plain generation (`grounding=False`): segmentation, campaign planning.
- Grounded generation (`grounding=True`): deep research / social-handle finding,
  using Gemini's built-in Google Search grounding tool.

Free tier note: `gemini-2.5-flash` runs on the free tier (incl. grounding).
The Gemini 3.x family currently requires billing (returns 429 on free keys).
"""

import asyncio

import httpx
import structlog

from apps.api.config import settings

logger = structlog.get_logger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-2.5-flash"
_MAX_ATTEMPTS = 3


class GeminiError(RuntimeError):
    """Raised when the Gemini API call fails or returns no usable content."""


async def gemini_generate(
    prompt: str,
    *,
    grounding: bool = False,
    max_output_tokens: int = 4096,
    model: str | None = None,
) -> str:
    """Call Gemini generateContent and return the concatenated text.

    Retries transient errors (timeouts, 5xx) with exponential backoff.
    Raises GeminiError on missing key or non-retryable API errors (4xx incl. 429).
    """
    if not settings.gemini_api_key:
        raise GeminiError("GEMINI_API_KEY is not configured")

    model = model or settings.gemini_model or DEFAULT_MODEL
    gen_config: dict = {"maxOutputTokens": max_output_tokens}
    if not grounding:
        # gemini-2.5-flash enables "thinking" by default. For deterministic JSON
        # tasks (segmentation, campaign planning) thinking adds ~60-100s latency
        # (blowing the client timeout) and consumes the output-token budget
        # (empty response -> JSON parse failure). Disable it here; grounded calls
        # (deep research) keep thinking because they genuinely benefit from it.
        gen_config["thinkingConfig"] = {"thinkingBudget": 0}
    body: dict = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": gen_config,
    }
    if grounding:
        body["tools"] = [{"google_search": {}}]

    url = GEMINI_URL.format(model=model)
    last_exc: Exception | None = None

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(url, params={"key": settings.gemini_api_key}, json=body)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last_exc = e
            if attempt < _MAX_ATTEMPTS:
                await asyncio.sleep(2 ** attempt)
                continue
            raise GeminiError(f"Gemini API transport error: {e}") from e

        if resp.status_code == 200:
            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return ""
            parts = candidates[0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts if "text" in p).strip()

        # 5xx → retry; 4xx (400/401/403/429) → fail fast (retrying won't help)
        try:
            msg = resp.json().get("error", {}).get("message", resp.text[:200])
        except Exception:
            msg = resp.text[:200]

        if resp.status_code >= 500 and attempt < _MAX_ATTEMPTS:
            logger.warning("gemini_retry", status=resp.status_code, attempt=attempt)
            await asyncio.sleep(2 ** attempt)
            continue
        raise GeminiError(f"Gemini API error {resp.status_code}: {msg}")

    raise GeminiError(f"Gemini API failed after {_MAX_ATTEMPTS} attempts: {last_exc}")
