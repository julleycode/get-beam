"""Per-row Identify must report the REAL skip reason, never a canned
"daily budget used up" line.

Regression: a max-plan site (no caps possible) saw "Not resolved — daily
budget used up or attempted in the last 30 days" when clicking Identify on a
privacy-opted-out (do_not_resolve) visitor. The true cause was a policy block.
"""

from apps.api.routers.visitors import _SKIP_REASON_MESSAGES

# Every reason _resolution_skip_reason() can return. If it grows a new reason
# without copy here, resolve_one_visitor falls back to a vague line and the bug
# is back — this set is the guard.
EXPECTED_REASONS = {
    "privacy_opt_out",
    "below_intent_threshold",
    "no_ip_address",
    "recently_attempted",
    "daily_budget_exhausted",
    "monthly_plan_limit_reached",
    "awaiting_next_run",
}


def test_every_skip_reason_has_a_message():
    missing = EXPECTED_REASONS - set(_SKIP_REASON_MESSAGES)
    assert not missing, f"skip reasons with no user-facing message: {missing}"


def test_privacy_opt_out_is_not_worded_as_a_limit():
    msg = _SKIP_REASON_MESSAGES["privacy_opt_out"].lower()
    # Must NOT repeat the old false "budget used up / attempted in 30 days" line.
    assert "budget used up" not in msg and "attempted in the last" not in msg, msg
    # Must name the real cause.
    assert any(w in msg for w in ("opt", "privacy", "suppress")), msg
