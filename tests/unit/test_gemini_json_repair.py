"""Unit tests for gemini_generate_json (JSON self-correction). No DB, no network.

Patches gemini_generate at the gemini_client module level — the layer
gemini_generate_json calls through — so the repair logic runs for real.
"""

import pytest

from apps.api.services import gemini_client
from apps.api.services.gemini_client import GeminiError, gemini_generate_json

pytestmark = pytest.mark.unit


def _script(monkeypatch, outputs: list):
    """Replay `outputs` per call (str => return it, Exception => raise it).

    The last entry repeats when calls outnumber outputs. Returns the list of
    prompts seen so tests can assert on the repair prompt.
    """
    prompts: list[str] = []

    async def fake_generate(prompt, **kwargs):
        out = outputs[min(len(prompts), len(outputs) - 1)]
        prompts.append(prompt)
        if isinstance(out, Exception):
            raise out
        return out

    monkeypatch.setattr(gemini_client, "gemini_generate", fake_generate)
    return prompts


@pytest.mark.asyncio
async def test_good_json_first_try(monkeypatch):
    prompts = _script(monkeypatch, ['{"segments": []}'])
    result = await gemini_generate_json("PROMPT")
    assert result == {"segments": []}
    assert len(prompts) == 1


@pytest.mark.asyncio
async def test_bad_then_good_repairs_with_feedback(monkeypatch):
    prompts = _script(monkeypatch, ["not json at all", '{"ok": true}'])
    result = await gemini_generate_json("PROMPT")
    assert result == {"ok": True}
    assert len(prompts) == 2
    repair = prompts[1]
    # Repair prompt = original + correction block + previous output fenced as data.
    assert repair.startswith("PROMPT")
    assert "CORRECTION REQUIRED" in repair
    assert "no JSON object" in repair
    assert "<untrusted_visitor_data>" in repair
    assert "not json at all" in repair


@pytest.mark.asyncio
async def test_validation_error_triggers_repair(monkeypatch):
    prompts = _script(monkeypatch, ['{"wrong": 1}', '{"segments": []}'])

    def validate(parsed: dict) -> str | None:
        return None if isinstance(parsed.get("segments"), list) else "segments missing"

    result = await gemini_generate_json("PROMPT", validate=validate)
    assert result == {"segments": []}
    assert len(prompts) == 2
    assert "segments missing" in prompts[1]


@pytest.mark.asyncio
async def test_parse_exhaustion_raises_valueerror(monkeypatch):
    prompts = _script(monkeypatch, ["still not json"])
    with pytest.raises(ValueError):
        await gemini_generate_json("PROMPT")
    # 1 initial try + 2 repairs (settings default) = exactly 3 model calls.
    assert len(prompts) == 3


@pytest.mark.asyncio
async def test_validate_exhaustion_returns_last_parsed(monkeypatch):
    # Output parses but never validates — exhaustion hands the dict back so
    # the caller's defensive normalization keeps today's behavior.
    prompts = _script(monkeypatch, ['{"touchpoints": "oops"}'])
    result = await gemini_generate_json(
        "PROMPT", validate=lambda p: '"touchpoints" must be a list'
    )
    assert result == {"touchpoints": "oops"}
    assert len(prompts) == 3


@pytest.mark.asyncio
async def test_transport_error_propagates_immediately(monkeypatch):
    prompts = _script(monkeypatch, [GeminiError("quota exceeded")])
    with pytest.raises(GeminiError):
        await gemini_generate_json("PROMPT")
    assert len(prompts) == 1  # no repair on transport failures


@pytest.mark.asyncio
async def test_repair_attempts_override(monkeypatch):
    prompts = _script(monkeypatch, ["nope"])
    with pytest.raises(ValueError):
        await gemini_generate_json("PROMPT", max_repair_attempts=0)
    assert len(prompts) == 1
