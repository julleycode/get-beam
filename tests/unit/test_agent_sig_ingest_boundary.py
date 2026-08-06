"""WS2 agent_sig ingest boundary — schema whitelist + bounds (SPEC AC-4/AC-7).

``POST /ingest`` is public and unauthenticated, so ``_asig`` is attacker-supplied
and lands in JSONB on the largest table in the schema. The Pydantic validator in
``apps/api/schemas/events.py`` is the only thing standing between a hostile client
and unbounded stored JSON, so it gets its own tests rather than relying on the
Docker-gated integration tier.

Also pins the two properties the batch sweep depends on: the abbreviated wire
keys survive round-trip, and an absent/garbage object normalises to None so
``_extract_agent_sig`` fails safe (flags nobody) instead of raising.
"""

import pytest

from apps.api.schemas.events import Event

pytestmark = pytest.mark.unit


def _event(**extra) -> Event:
    return Event.model_validate({"type": "click", "ts": "2026-08-07T00:00:00Z", **extra})


# ─── happy path: the real pixel shape survives intact ───


def test_pixel_wire_shape_round_trips():
    ev = _event(_asig={"w": False, "h": False, "p": 0, "d": 2, "c": 7})
    assert ev.agent_sig == {"w": False, "h": False, "p": 0.0, "d": 2, "c": 7}


def test_absent_agent_sig_is_none():
    assert _event().agent_sig is None


# ─── the boundary: everything else is dropped or clamped ───


def test_unknown_keys_are_dropped():
    ev = _event(_asig={"w": True, "evil": "x" * 10_000, "nested": {"a": [1, 2, 3]}})
    assert ev.agent_sig == {"w": True}


def test_object_with_no_known_keys_normalises_to_none():
    """Fails safe: the sweep treats None as "absent" and never flags."""
    assert _event(_asig={"junk": 1}).agent_sig is None
    assert _event(_asig={}).agent_sig is None


def test_non_dict_payload_is_rejected_to_none():
    for bad in ("string", 123, [1, 2, 3], True):
        assert _event(_asig=bad).agent_sig is None, f"{bad!r} should not persist"


def test_counters_are_clamped_not_trusted():
    ev = _event(_asig={"d": 10**9, "c": -5})
    assert ev.agent_sig == {"d": 10_000, "c": 0}


def test_entropy_is_clamped_to_unit_interval():
    assert _event(_asig={"p": 99.0}).agent_sig == {"p": 1.0}
    assert _event(_asig={"p": -3}).agent_sig == {"p": 0.0}


def test_uncoercible_values_are_dropped_not_raised():
    """A malformed field must never 400 the whole batch (AC-7: never drop)."""
    ev = _event(_asig={"p": "not-a-number", "d": None, "c": 4})
    assert ev.agent_sig == {"c": 4}


def test_truthy_coercion_for_the_boolean_signals():
    ev = _event(_asig={"w": 1, "h": 0})
    assert ev.agent_sig == {"w": True, "h": False}
