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
