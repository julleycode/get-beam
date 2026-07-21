"""Integration test: segmentation JSON self-correction end-to-end.

A garbage first model output must trigger one repair re-prompt; the repaired
output then flows through the normal segment-creation path (hallucinated-id
filtering included). Gemini is mocked at the gemini_client layer UNDER
gemini_generate_json so the repair logic itself runs for real.

Requires: PostgreSQL running locally (via docker-compose).
"""

import json
import uuid as uuidlib
from datetime import datetime, timezone

import pytest

from apps.api.agents.segmenter import run_segmentation
from apps.api.config import settings
from apps.api.models.visitor import Visitor
from apps.api.services import gemini_client

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_bad_json_then_repaired_creates_segments(test_db, monkeypatch):
    site_id = f"seg_repair_{uuidlib.uuid4().hex[:8]}"
    visitor_ids = [f"v{i}_{uuidlib.uuid4().hex[:6]}" for i in range(3)]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    visitors = [
        Visitor(
            site_id=site_id,
            visitor_id=vid,
            first_seen=now,
            last_seen=now,
            intent_score=80.0,
            enrichment_status="enriched",
        )
        for vid in visitor_ids
    ]
    for v in visitors:
        test_db.add(v)
    await test_db.commit()

    good_output = json.dumps(
        {
            "segments": [
                {
                    "segment_id": "seg_001",
                    "name": "Hot leads",
                    "description": "High intent visitors",
                    "visitor_ids": visitor_ids + ["hallucinated_id"],
                    "characteristics": {"avg_intent_score": 80},
                    "recommended_channels": ["email"],
                    "messaging_angle": "act now",
                    "priority": "high",
                }
            ],
            "unsegmented_visitor_ids": [],
            "reasoning": "test",
        }
    )
    prompts: list[str] = []

    async def fake_generate(prompt, **kwargs):
        prompts.append(prompt)
        return "```oops not json```" if len(prompts) == 1 else good_output

    monkeypatch.setattr(gemini_client, "gemini_generate", fake_generate)
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")

    segments = await run_segmentation(
        db=test_db,
        site_id=site_id,
        site_name="Repair Site",
        site_description="",
        site_category="",
        visitors=visitors,
    )

    assert len(prompts) == 2, "one repair re-prompt expected"
    assert "CORRECTION REQUIRED" in prompts[1]
    assert len(segments) == 1
    # The hallucinated id was filtered; only the 3 real members counted.
    assert segments[0].visitor_count == 3
    assert segments[0].name == "Hot leads"
