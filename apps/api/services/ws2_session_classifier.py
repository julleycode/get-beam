"""WS2 agent-driven session classifier — pure signal functions (AC-WS2-1/8).

The SIXTH, ORTHOGONAL detection layer. Beam's five existing layers (tracker.js
webdriver check, bot_filter UA regex, agent_classifier self-declaring vendor
list, ingest_velocity flood shape, cadence_bot_flag cron-cadence) each reason
about identity strings, short-window traffic shape, or long-run visit cadence.
A human-SHAPED but agent-OPERATED browser session (Comet, Claude-in-Chrome,
Playwright/CDP automation) with a convincing UA and normal volume sails past all
five and shows up as an ordinary visitor.

This module looks at WITHIN-SESSION BEHAVIOR instead, in two stages:

    Stage 1 — deterministic fast-path. navigator.webdriver / a HeadlessChrome
              UA-CH token → agent-operated immediately (near-zero FPR when
              present). Reachable in real traffic since 07-08-26: tracker.js's
              navigator.webdriver early-return, which used to discard these very
              sessions before any signal could be recorded, was deleted by the WS2
              activation. NOTE: a measured feasibility probe (07-08-26) found
              extension-driven agentic browsers (Claude-in-Chrome) report
              webdriver=false with human-identical UA-CH brands, so Stage 1 alone
              does NOT cover that product class — Stage 2 below is load-bearing
              for it, not a fallback.

    Stage 2 — behavioral AND-gate fallback. LOW pointer entropy AND a HIGH
              dead-centre-click rate. A strict conjunction (AC-WS2 dual-signal
              design), mirroring cadence_bot_flag / ingest_velocity: requiring
              BOTH is what keeps the false positive out (a human with a shaky
              trackpad has high entropy; a human clicking naturally rarely lands
              dead-centre repeatedly, so neither alone fires).

Sample-size preconditions are evaluated BEFORE any ratio math (same shape as
cadence_bot_flag): a session with too few clicks is noise, not a behavior.

Thresholds are ALWAYS passed IN (never read from settings here, no module-level
magic number) so the caller is forced to source them from operator-tunable config.

DELIBERATELY IMPORTS NOTHING from cadence_bot_flag.py or agent_classifier.py —
this is a parallel layer, not a derived one (INNOVATE decision D2, enforced by
tests/unit/test_ws2_zero_import.py).

VISIBILITY-ONLY (AC-WS2-8 / AC-G-4). Nothing here — and nothing that consumes it
— is read by is_emailable_identity(), sets do_not_resolve/is_abuse_flagged, joins
agent_visits, or enters any render/redirect/blocking path. Pure functions, zero
I/O, zero DB session, zero imports outside the stdlib.
"""


def is_deterministic_agent(webdriver: bool | None, ua_ch_headless: bool | None) -> bool:
    """Stage 1 fast-path. True when a hard automation artifact is present.

    Either signal alone is sufficient — both are near-zero-FPR tells. None is
    treated as "absent" (the common real-traffic case), so a missing signal never
    forces a positive.
    """
    return bool(webdriver) or bool(ua_ch_headless)


def compute_dead_center_rate(dead_center_ct: int | None, click_ct: int | None) -> float:
    """Fraction of clicks that landed dead-centre on their target. Pure, no I/O.

    Returns 0.0 for zero/absent clicks — never divides by zero. A 0.0 rate is
    safe because the caller's separate min-clicks precondition gates the decision
    before this value can matter.
    """
    if not click_ct or click_ct <= 0:
        return 0.0
    centered = dead_center_ct or 0
    return centered / click_ct


def evaluate_behavioral_and_gate(
    pointer_entropy: float | None,
    dead_center_rate: float,
    min_clicks_met: bool,
    max_pointer_entropy_threshold: float,
    min_dead_center_rate_threshold: float,
) -> bool:
    """Stage 2 pure decision — True when the session BEHAVES like an agent.

    Structural sibling of ``cadence_bot_flag.evaluate_cadence_bot_flag`` and
    ``ingest_velocity.evaluate_velocity``: precondition-before-ratio, then a
    strict conjunction. LOW pointer entropy AND HIGH dead-centre-click rate.

    Both thresholds are passed IN (never read from settings here) so the module
    carries no magic number and the caller is forced to source them from
    operator-tunable config.
    """
    if not min_clicks_met:
        return False
    if pointer_entropy is None:
        return False
    return (
        pointer_entropy <= max_pointer_entropy_threshold
        and dead_center_rate >= min_dead_center_rate_threshold
    )


def evaluate_session_classifier(
    webdriver: bool | None,
    ua_ch_headless: bool | None,
    pointer_entropy: float | None,
    dead_center_rate: float,
    min_clicks_met: bool,
    max_pointer_entropy_threshold: float,
    min_dead_center_rate_threshold: float,
) -> bool:
    """Top-level staged decision — True when this session looks agent-operated.

    Stage 1 (deterministic fast-path) short-circuits; otherwise fall through to
    Stage 2 (behavioral AND-gate). Mirrors the staged shape locked in INNOVATE
    decision D2. All thresholds passed in; no settings read here.
    """
    if is_deterministic_agent(webdriver, ua_ch_headless):
        return True
    return evaluate_behavioral_and_gate(
        pointer_entropy,
        dead_center_rate,
        min_clicks_met,
        max_pointer_entropy_threshold,
        min_dead_center_rate_threshold,
    )
