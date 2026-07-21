"""Unit tests for the agent JSON validators that drive repair retries."""

import pytest

from apps.api.agents.campaign_planner import _validate_plan
from apps.api.agents.segmenter import _validate_segmentation

pytestmark = pytest.mark.unit


def test_segmentation_validator_accepts_valid_shapes():
    assert _validate_segmentation({"segments": []}) is None
    assert _validate_segmentation({"segments": [{"name": "Hot leads"}]}) is None


def test_segmentation_validator_rejects_invalid_shapes():
    assert _validate_segmentation({}) is not None
    assert _validate_segmentation({"segments": "nope"}) is not None
    assert _validate_segmentation({"segments": ["nope"]}) is not None


def test_plan_validator_accepts_valid_shapes():
    assert _validate_plan({"touchpoints": []}) is None
    assert _validate_plan({"touchpoints": [{"order": 1, "channel": "email"}]}) is None


def test_plan_validator_rejects_invalid_shapes():
    assert _validate_plan({}) is not None
    assert _validate_plan({"touchpoints": "x"}) is not None
    assert _validate_plan({"touchpoints": [1, {"order": 2}]}) is not None
