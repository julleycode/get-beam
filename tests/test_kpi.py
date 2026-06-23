"""Unit tests for the KPI rate derivation (pure — no DB)."""

from apps.api.services.kpi import derive_rates


def test_basic_rates() -> None:
    # 100 visitors, 40 identified, 20 high-intent, acted on 15 of them.
    r = derive_rates(visitors=100, identified=40, high_intent=20, acted_high=15)
    assert r == {"identify_rate": 0.4, "action_rate": 0.75}


def test_zero_visitors_no_divide_by_zero() -> None:
    assert derive_rates(0, 0, 0, 0) == {"identify_rate": 0.0, "action_rate": 0.0}


def test_acted_capped_at_high_intent() -> None:
    # acted_high can exceed high_intent if a draft outlives the intent window;
    # the rate must never exceed 1.0.
    r = derive_rates(visitors=10, identified=5, high_intent=2, acted_high=5)
    assert r["action_rate"] == 1.0


def test_no_high_intent_action_rate_zero() -> None:
    r = derive_rates(visitors=50, identified=10, high_intent=0, acted_high=0)
    assert r["action_rate"] == 0.0
    assert r["identify_rate"] == 0.2
