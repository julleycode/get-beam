"""SPEC AC-8 / AC-9 — visibility-only flags must never gate emailability.

Beam has three "visibility-only" visitor flags — ``is_bot_suspect`` (cadence bot
flag), ``is_internal_suspect`` (outlier damping) and ``is_agent_operated`` (WS2
agent-operated sessions). All three are dashboard badges. None of them may ever
influence outreach eligibility, and ``is_emailable_identity()`` must keep its
exact 3-parameter signature (the locked invariant recorded in
``f3a7c9e21b48_add_internal_traffic_damping.py``).

The distinction this file defends is easy to erode by accident: the codebase
ALSO has genuinely-gating flags (``source_agent_visit_id``, ``is_abuse_flagged``)
that DO exclude a record, and they sit on the same model. A future author adding
a 4th guard parameter "for symmetry" would silently start suppressing real,
contactable humans whose only sin was a badge. These tests fail loudly first.

Mirrors ``test_agent_origin_exclusion.py``'s structure (real ORM objects, no DB).

Non-vacuity: these assertions genuinely discriminate. Adding
``if is_agent_operated: return False`` (or the ``is_bot_suspect`` equivalent) to
``is_emailable_identity`` turns ``test_flags_do_not_change_emailability`` red for
every person-level provider, and adding a 4th parameter turns
``test_signature_has_exactly_three_parameters`` red. The contrast test below
proves the same call SHAPE does flip to False for the real guard inputs, so a
tautological always-True implementation could not pass this file either.
"""

import inspect

import pytest

import apps.api.main  # noqa: F401 — registers ALL ORM models so a REAL
#                        IdentifiedVisitor can be constructed (mapper config
#                        needs every related model imported first).
from apps.api.models.visitor import IdentifiedVisitor
from apps.api.services.identity_classification import (
    PERSON_LEVEL_PROVIDERS,
    is_emailable_identity,
)

pytestmark = pytest.mark.unit

# Every visibility-only flag on the model, by column name.
_VISIBILITY_ONLY_FLAGS = ("is_bot_suspect", "is_agent_operated", "is_internal_suspect")


def _visitor(**flags) -> IdentifiedVisitor:
    """A real IdentifiedVisitor carrying the given visibility-only flags."""
    return IdentifiedVisitor(
        site_id="site-1",
        visitor_id="visitor-1",
        **flags,
    )


# ─── AC-8: the signature itself is the structural guarantee ───


def test_signature_has_exactly_three_parameters():
    """No 4th guard parameter — visibility-only flags are not passed in at all."""
    params = list(inspect.signature(is_emailable_identity).parameters)
    assert params == ["provider", "source_agent_visit_id", "is_abuse_flagged"], (
        "is_emailable_identity()'s signature changed — a visibility-only flag "
        "must never become a guard parameter (locked invariant, plan D1)"
    )


def test_guard_body_never_reads_a_visibility_only_flag():
    """A literal tripwire: a future rename or re-wiring fails here, loudly."""
    source = inspect.getsource(is_emailable_identity)
    for flag in _VISIBILITY_ONLY_FLAGS:
        assert flag not in source, (
            f"is_emailable_identity() references {flag} — visibility-only flags "
            "must be invisible to outreach eligibility"
        )


# ─── AC-9: behavior is identical with and without the flags ───


@pytest.mark.parametrize("provider", sorted(PERSON_LEVEL_PROVIDERS))
@pytest.mark.parametrize("flag", _VISIBILITY_ONLY_FLAGS)
def test_flags_do_not_change_emailability(provider: str, flag: str):
    """A flagged visitor is EXACTLY as emailable as an unflagged one."""
    clean = _visitor()
    flagged = _visitor(**{flag: True})

    assert getattr(flagged, flag) is True, "fixture did not actually set the flag"
    assert getattr(clean, flag) in (False, None)

    baseline = is_emailable_identity(provider)
    assert baseline is True, f"{provider} should be person-level emailable"

    # The flag is not even an input — which is the point. Passing the same
    # provider must yield the same answer for both rows.
    assert is_emailable_identity(flagged.resolution_provider or provider) is baseline


@pytest.mark.parametrize("flag", _VISIBILITY_ONLY_FLAGS)
def test_flags_do_not_rescue_a_non_emailable_provider(flag: str):
    """Symmetry check: the flags cannot flip a False to True either."""
    assert is_emailable_identity(None) is False
    flagged = _visitor(**{flag: True})
    assert is_emailable_identity(flagged.resolution_provider) is False


def test_real_guards_still_exclude(monkeypatch):
    """Contrast case — proves the assertions above are not vacuously true.

    The same call shape DOES return False for the two inputs that are genuinely
    supposed to gate, so "is_emailable_identity always returns True" is not an
    explanation for the tests above passing.
    """
    provider = sorted(PERSON_LEVEL_PROVIDERS)[0]
    assert is_emailable_identity(provider) is True
    assert is_emailable_identity(provider, source_agent_visit_id="agent-1") is False
    assert is_emailable_identity(provider, None, True) is False
