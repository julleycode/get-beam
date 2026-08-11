"""WS2 farbled marker — ingest boundary (schema coercion).

``POST /ingest`` is public and unauthenticated, so ``_fb`` is attacker-supplied.
The Pydantic validator in ``apps/api/schemas/events.py`` uses ``mode="before"``
specifically so a malformed optional signal degrades to ``False`` instead of
raising a ValidationError that would 422 the WHOLE batch — one junk field must
never drop a page's worth of legitimate events.

These tests pin exactly that: every shape coerces, nothing raises, and the batch
still parses.
"""

import pytest

from apps.api.schemas.events import Event, EventBatch

pytestmark = pytest.mark.unit


def _event(**extra) -> Event:
    return Event.model_validate({"type": "click", "ts": "2026-08-10T00:00:00Z", **extra})


# ─── happy path ───


def test_absent_marker_defaults_false():
    """Older pixel builds and every pre-probe event in a session omit _fb."""
    assert _event().farbled is False


def test_pixel_wire_shape_sets_true():
    """The pixel sends the integer 1, not a JSON bool."""
    assert _event(_fb=1).farbled is True


def test_explicit_bool_round_trips():
    assert _event(_fb=True).farbled is True
    assert _event(_fb=False).farbled is False


# ─── the boundary: nothing raises ───


@pytest.mark.parametrize("bad", ["yes", {}, None, [], 0, "", [1, 2], {"a": 1}, 3.7])
def test_garbage_coerces_and_never_raises(bad):
    ev = _event(_fb=bad)
    assert isinstance(ev.farbled, bool)


def test_malformed_marker_does_not_reject_the_batch():
    """The whole point of mode="before": one junk signal must not 422 a batch."""
    batch = EventBatch.model_validate({
        "site_id": "s1",
        "visitor_id": "v1",
        "events": [
            {"type": "pageview", "ts": "2026-08-10T00:00:00Z", "_fb": {"nope": True}},
            {"type": "click", "ts": "2026-08-10T00:00:01Z", "_fb": 1},
        ],
    })
    assert len(batch.events) == 2
    assert batch.events[1].farbled is True


def test_marker_is_independent_of_optout():
    """farbled is NOT a privacy flag and must never be conflated with optout."""
    ev = _event(_fb=1)
    assert ev.farbled is True
    assert ev.optout is False
