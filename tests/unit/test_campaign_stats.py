"""AC-2 / AC-13 (rollup half): the pure `summarize` funnel.

Proves the measurement-honesty rules: no sends is NOT a measured zero, N sends
with 0 opens IS a measured zero, every open-rate value carries the MPP caveat,
and `channel="email"` excludes social rows.

No flag precondition — `summarize` is pure and ungated. In particular it is NOT
gated on `identity_signals_enabled`, which covers identity corroboration, not
campaign open/click.
"""

from datetime import datetime

import pytest

from apps.api.services.campaign_stats import (
    OPEN_RATE_CAVEAT,
    CampaignStats,
    TouchpointRow,
    summarize,
)

pytestmark = pytest.mark.unit

_T = datetime(2026, 8, 1)


def _row(channel="email", status="sent", opened=None, clicked=None):
    return TouchpointRow(
        channel=channel, status=status, opened_at=opened, clicked_at=clicked
    )


def test_zero_sends_is_no_data_not_a_measured_zero():
    stats = summarize([])
    assert stats.sends == 0
    assert stats.has_data is False
    # The whole point: None, never 0.0. A 0% open rate is a CLAIM about a
    # measurement that never happened.
    assert stats.open_rate is None
    assert stats.click_rate is None


def test_sends_with_no_opens_is_a_measured_zero():
    stats = summarize([_row(), _row(), _row()])
    assert stats.sends == 3
    assert stats.has_data is True
    assert stats.open_rate == 0.0  # measured, not missing


def test_open_and_click_rates_computed_over_sends():
    rows = [
        _row(opened=_T, clicked=_T),
        _row(opened=_T),
        _row(),
        _row(),
    ]
    stats = summarize(rows)
    assert stats.sends == 4
    assert stats.opens == 2
    assert stats.clicks == 1
    assert stats.open_rate == 0.5
    assert stats.click_rate == 0.25


def test_channel_email_filter_excludes_social_rows():
    rows = [
        _row(channel="email", opened=_T),
        _row(channel="social_reply", opened=_T),
        _row(channel="social_dm", clicked=_T),
    ]
    filtered = summarize(rows, channel="email")
    assert filtered.sends == 1
    assert filtered.opens == 1
    assert filtered.clicks == 0
    # Unfiltered still counts everything — /outcomes has never filtered on
    # channel, so the default must not silently change its numbers.
    unfiltered = summarize(rows)
    assert unfiltered.sends == 3
    assert unfiltered.opens == 2
    assert unfiltered.clicks == 1


def test_non_sent_status_rows_do_not_count_as_sends():
    stats = summarize([_row(status="pending"), _row(status="failed"), _row()])
    assert stats.sends == 1


def test_conversions_passed_through():
    assert summarize([_row()], conversions=7).conversions == 7


def test_summarize_is_pure_and_repeatable():
    rows = [_row(opened=_T), _row()]
    first = summarize(rows, channel="email")
    second = summarize(rows, channel="email")
    assert first == second
    assert isinstance(first, CampaignStats)


def test_open_rate_caveat_names_both_failure_directions():
    # The caveat must state BOTH directions — overcount and undercount — or a
    # reader treats an open rate as merely noisy rather than unreliable.
    lowered = OPEN_RATE_CAVEAT.lower()
    assert "apple mail privacy protection" in lowered
    assert "overcount" in lowered
    assert "undercount" in lowered
    assert "clicks are the reliable signal" in lowered
