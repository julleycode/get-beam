"""G1 / AC-4 — deterministic winning-ad ranking (ad-insights-seo-aeo)."""

import ast
import pathlib
import random
from datetime import date

import pytest

from apps.api.services.ad_insights_rank import headline_angles, rank_ads, winning_angles

pytestmark = pytest.mark.unit

RANK_PATH = (
    pathlib.Path(__file__).resolve().parents[2] / "apps" / "api" / "services" / "ad_insights_rank.py"
)


def _row(ad_id, imp, clk, conv, headline="", provider="meta", day=date(2026, 11, 1)):
    return {
        "platform_ad_id": ad_id, "provider": provider, "date": day,
        "impressions": imp, "clicks": clk, "conversions": conv, "headline": headline,
        "body": "", "landing_url": f"https://x.com/{ad_id}", "campaign_name": "c",
    }


def test_floor_excludes_low_impression_ads():
    rows = [_row("a", 499, 100, 50), _row("b", 500, 10, 1)]
    out = rank_ads(rows, min_impressions=500)
    assert [a.platform_ad_id for a in out] == ["b"]


def test_daily_rows_are_aggregated_before_the_floor():
    rows = [_row("a", 300, 30, 3, day=date(2026, 11, 1)), _row("a", 300, 30, 3, day=date(2026, 11, 2))]
    out = rank_ads(rows, min_impressions=500)
    assert len(out) == 1 and out[0].impressions == 600 and out[0].clicks == 60


def test_score_is_ctr_rank_plus_conv_rank():
    rows = [
        _row("hi_ctr", 1000, 100, 1),   # ctr 1st, conv 3rd -> 4
        _row("hi_conv", 1000, 20, 10),  # ctr 3rd, conv 1st -> 4
        _row("both", 1000, 50, 10),     # ctr 2nd, conv 2nd -> 4
        _row("worst", 1000, 5, 0),      # 4th + 4th -> 8
    ]
    out = rank_ads(rows, min_impressions=1)
    assert out[-1].platform_ad_id == "worst"
    # three-way tie at score 4 -> platform_ad_id order
    assert [a.platform_ad_id for a in out[:3]] == ["both", "hi_conv", "hi_ctr"]
    assert [a.rank for a in out] == [1, 2, 3, 4]


def test_ranking_is_deterministic_under_input_shuffle():
    rows = [_row(f"ad{i}", 1000 + i, (i * 7) % 50, (i * 3) % 5) for i in range(20)]
    expected = [a.platform_ad_id for a in rank_ads(rows, min_impressions=500)]
    for seed in range(5):
        shuffled = rows[:]
        random.Random(seed).shuffle(shuffled)
        assert [a.platform_ad_id for a in rank_ads(shuffled, min_impressions=500)] == expected


def test_top_five_only():
    rows = [_row(f"ad{i}", 1000, i + 1, 1) for i in range(9)]
    assert len(rank_ads(rows, min_impressions=1)) == 5


def test_angles_drop_stopword_edges():
    grams = headline_angles("Find who visits your site")
    assert "find" in grams and "visits your site" in grams
    assert all(not g.startswith("your ") for g in grams)


def test_winning_angles_prefer_recurring():
    rows = [_row("a", 1000, 50, 5, "Identify website visitors"), _row("b", 1000, 40, 4, "Website visitors to leads")]
    out = rank_ads(rows, min_impressions=1)
    assert winning_angles(out)[0] == "website visitors"


def test_module_has_zero_db_or_io_imports():
    tree = ast.parse(RANK_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"re", "dataclasses", "typing"}, imported
