"""Pure, deterministic winning-ad ranker (ad-insights-seo-aeo_27-11-26, B1).

ZERO DB / IO imports (AST-gated in tests/unit/test_ad_insights_rank.py):
ranking is arithmetic, not a model call.

score = CTR rank + conversion-rate rank (rank 1 = best); lower score wins;
ties broken by platform_ad_id. Ads whose aggregated impressions are below the
floor are excluded before ranking.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9'\-]*")
_STOPWORDS = frozenset(
    "a an and are as at be by for from has have how in is it its of on or our "
    "that the this to was we with you your yours without".split()
)


@dataclass
class RankedAd:
    platform_ad_id: str
    provider: str
    headline: str = ""
    body: str = ""
    landing_url: str = ""
    campaign_name: str = ""
    impressions: int = 0
    clicks: int = 0
    conversions: float = 0.0
    ctr: float = 0.0
    conv_rate: float = 0.0
    score: int = 0
    rank: int = 0
    angles: list[str] = field(default_factory=list)


def _get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def aggregate(rows: Iterable[Any]) -> list[RankedAd]:
    """Sum daily rows per (provider, platform_ad_id); copy = latest non-empty."""
    by_ad: dict[tuple[str, str], RankedAd] = {}
    latest: dict[tuple[str, str], Any] = {}
    for r in rows:
        ad_id = str(_get(r, "platform_ad_id") or "")
        if not ad_id:
            continue
        provider = str(_get(r, "provider") or "")
        key = (provider, ad_id)
        ad = by_ad.setdefault(key, RankedAd(platform_ad_id=ad_id, provider=provider))
        ad.impressions += int(_get(r, "impressions") or 0)
        ad.clicks += int(_get(r, "clicks") or 0)
        ad.conversions += float(_get(r, "conversions") or 0)
        day = _get(r, "date")
        if _get(r, "headline") and (key not in latest or (day is not None and day >= latest[key])):
            latest[key] = day
            ad.headline = str(_get(r, "headline") or "")
            ad.body = str(_get(r, "body") or "")
            ad.landing_url = str(_get(r, "landing_url") or "")
            ad.campaign_name = str(_get(r, "campaign_name") or "")
    return list(by_ad.values())


def _ranks(ads: list[RankedAd], metric: str) -> dict[str, int]:
    ordered = sorted(ads, key=lambda a: (-getattr(a, metric), a.platform_ad_id, a.provider))
    return {f"{a.provider}:{a.platform_ad_id}": i + 1 for i, a in enumerate(ordered)}


def headline_angles(headline: str, max_n: int = 3) -> list[str]:
    """Lower-cased 1..max_n-grams with stopword-only grams dropped."""
    words = _WORD_RE.findall((headline or "").lower())
    grams: list[str] = []
    for n in range(1, max_n + 1):
        for i in range(len(words) - n + 1):
            gram = words[i : i + n]
            if all(w in _STOPWORDS for w in gram) or gram[0] in _STOPWORDS or gram[-1] in _STOPWORDS:
                continue
            grams.append(" ".join(gram))
    return grams


def rank_ads(rows: Iterable[Any], *, min_impressions: int, top_n: int = 5) -> list[RankedAd]:
    ads = [a for a in aggregate(rows) if a.impressions >= min_impressions]
    for a in ads:
        a.ctr = a.clicks / a.impressions if a.impressions else 0.0
        a.conv_rate = a.conversions / a.clicks if a.clicks else 0.0
    ctr_rank = _ranks(ads, "ctr")
    conv_rank = _ranks(ads, "conv_rate")
    for a in ads:
        k = f"{a.provider}:{a.platform_ad_id}"
        a.score = ctr_rank[k] + conv_rank[k]
    ads.sort(key=lambda a: (a.score, a.platform_ad_id, a.provider))
    top = ads[:top_n]
    for i, a in enumerate(top):
        a.rank = i + 1
        a.angles = headline_angles(a.headline)[:10]
    return top


def winning_angles(ads: list[RankedAd], limit: int = 10) -> list[str]:
    """Angles recurring across winners first, then by first appearance."""
    counts: dict[str, int] = {}
    order: dict[str, int] = {}
    for a in ads:
        for g in dict.fromkeys(headline_angles(a.headline)):
            counts[g] = counts.get(g, 0) + 1
            order.setdefault(g, len(order))
    return sorted(counts, key=lambda g: (-counts[g], -len(g.split()), order[g]))[:limit]
