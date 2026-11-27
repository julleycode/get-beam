"""AC-4 — the planner prompt documents {{booking_link}} with correct escaping.

CAMPAIGN_PLANNING_PROMPT is a brace-escaped ``.format()`` template: a token that
should reach the model as ``{{booking_link}}`` must be written
``{{{{booking_link}}}}`` in the source. Writing it unescaped either raises at
format time or emits a single-brace token.

There is no other campaign_planner test file in this repo (``-k campaign_planner``
collects zero tests), so this file is AC-4's only home.
"""

import pytest

from apps.api.agents.campaign_planner import CAMPAIGN_PLANNING_PROMPT

pytestmark = pytest.mark.unit


# CAMPAIGN_PLANNING_PROMPT.format() requires exactly these 9 kwargs; omitting
# any one raises KeyError.
_FORMAT_KWARGS = {
    "segment_name": "Warm SaaS founders",
    "segment_description": "Repeat visitors to pricing",
    "visitor_count": 12,
    "characteristics_json": "{}",
    "channels": "email",
    "messaging_angle": "value-led",
    "visitor_profiles_json": "[]",
    "segment_id": "seg_123",
    "connected_accounts_info": "none",
}


def test_prompt_formats_without_error():
    """.format() must succeed with all 9 kwargs — a mis-escaped brace raises."""
    rendered = CAMPAIGN_PLANNING_PROMPT.format(**_FORMAT_KWARGS)
    assert isinstance(rendered, str) and rendered


def test_rendered_prompt_contains_double_brace_booking_link():
    """The model must see {{booking_link}}, not {booking_link} or a KeyError."""
    rendered = CAMPAIGN_PLANNING_PROMPT.format(**_FORMAT_KWARGS)
    assert "{{booking_link}}" in rendered
    # Non-vacuity: the existing first_name token renders the same way, so this
    # asserts the escaping convention rather than an accident of the substring.
    assert "{{first_name}}" in rendered


def test_prompt_conditions_the_token_on_a_configured_booking_url():
    """AC-4: the model is told to use it ONLY when a booking URL exists."""
    rendered = CAMPAIGN_PLANNING_PROMPT.format(**_FORMAT_KWARGS)
    assert "ONLY if the site has a booking URL configured" in rendered


# ─── signal-creative-cta: flag-gated angle + CTA prompt sections (AC2/AC3) ───

from unittest.mock import AsyncMock, MagicMock  # noqa: E402

from apps.api.agents import campaign_planner  # noqa: E402

_PLAN = {
    "campaign_name": "c",
    "touchpoints": [
        {"channel": "email", "subject": "s", "body": "b {{cta_link}}", "cta_type": "pricing_page"},
        {"channel": "linkedin", "connection_note": "n"},
    ],
}


def _segment():
    seg = MagicMock()
    seg.id = "seg-1"
    seg.site_id = "site-1"
    seg.name = "Seg"
    seg.description = "d"
    seg.visitor_count = 2
    seg.characteristics = {}
    seg.recommended_channels = ["email"]
    seg.messaging_angle = "m"
    return seg


async def _plan(monkeypatch, *, creative: bool, cta: bool, site_row=None):
    import copy

    s = campaign_planner.settings
    monkeypatch.setattr(s, "gemini_api_key", "k")
    monkeypatch.setattr(s, "campaign_planner_tools_enabled", False)
    monkeypatch.setattr(s, "campaign_benchmark_enabled", False)
    monkeypatch.setattr(s, "icp_fit_enabled", False)
    monkeypatch.setattr(s, "signal_creative_enabled", creative)
    monkeypatch.setattr(s, "cta_types_enabled", cta)
    captured = {}

    async def _fake_json(prompt, **kw):
        captured["prompt"] = prompt
        return copy.deepcopy(_PLAN)

    monkeypatch.setattr(campaign_planner, "gemini_generate_json", _fake_json)
    row = MagicMock()
    row.first.return_value = site_row
    db = MagicMock()
    db.execute = AsyncMock(return_value=row)
    db.add = MagicMock()
    db.commit = AsyncMock()
    profiles = [
        {"visitor_id": "a", "pages_visited": ["/pricing"], "total_sessions": 1},
        {"visitor_id": "b", "pages_visited": ["/pricing"], "total_sessions": 1},
    ]
    campaign = await campaign_planner.plan_campaign(db, _segment(), profiles, [])
    return captured["prompt"], campaign.plan, db


@pytest.mark.asyncio
async def test_flag_off_prompt_and_plan_unchanged(monkeypatch):
    prompt, plan, db = await _plan(monkeypatch, creative=False, cta=False)
    assert "## Creative angle" not in prompt and "## Call to action" not in prompt
    assert "cta_link" not in prompt
    assert "signal_angle" not in plan
    assert plan["touchpoints"] == _PLAN["touchpoints"]  # no coercion
    db.execute.assert_not_called()  # zero extra queries flag-OFF


@pytest.mark.asyncio
async def test_flag_on_only_appends_to_flag_off_prompt(monkeypatch):
    off, _, _ = await _plan(monkeypatch, creative=False, cta=False)
    on, _, _ = await _plan(monkeypatch, creative=True, cta=False)
    assert on.startswith(off)
    assert on != off


@pytest.mark.asyncio
async def test_flag_on_contains_angle_and_cta_list_and_coerces(monkeypatch):
    cfg = {"default": "free_trial", "types": {"free_trial": {"url": "https://acme.com/t"}}}
    prompt, plan, _ = await _plan(
        monkeypatch, creative=True, cta=True, site_row=(cfg, "https://cal.com/a")
    )
    assert "Angle: pricing_intent" in prompt
    assert '"book_demo", "free_trial", "reply"' in prompt
    assert "{{cta_link}}" in prompt
    assert plan["signal_angle"] == "pricing_intent"
    # pricing_page unavailable → coerced to the site default.
    assert plan["touchpoints"][0]["cta_type"] == "free_trial"
    assert "cta_type" not in plan["touchpoints"][1]
