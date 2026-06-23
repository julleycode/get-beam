"""Conviction line — a one-line "why this person is worth reaching out to",
built deterministically from signals beam already has (no LLM cost or latency).

This closes the gap between "I see a name" and "I'll actually message them": the
founder's confidence to send comes from knowing *why* this visitor matters. We
compose the strongest 2-3 signals available — role/company, return visits, the
pages they hit, attention depth — plus the intent score.
"""

# Substrings in a page path that signal buying intent.
_HOT_PAGES = (
    ("pricing", "pricing"),
    ("/demo", "demo"),
    ("signup", "signup"),
    ("sign-up", "signup"),
    ("trial", "trial"),
    ("checkout", "checkout"),
    ("contact", "contact"),
    ("/book", "booking"),
)

HIGH_INTENT = 40


def _hot_page(pages: list[str] | None) -> str | None:
    """The first buying-intent page among those visited, normalised to a label."""
    for p in pages or []:
        pl = (p or "").lower()
        for needle, label in _HOT_PAGES:
            if needle in pl:
                return label
    return None


def build_conviction(d: dict) -> str | None:
    """Return a short "why this person" line, or None when there's nothing worth
    saying. `d` is a dict of visitor fields (plus enrichment on the detail view).
    Pure — unit-testable."""
    parts: list[str] = []

    # Who they are — only present once enriched (detail view).
    job = (d.get("job_title") or "").strip()
    company = (d.get("company_name") or "").strip()
    if job and company:
        parts.append(f"{job} at {company}")
    elif job:
        parts.append(job)
    elif company:
        parts.append(f"works at {company}")

    # Repeat visits are the clearest behavioural tell.
    sessions = int(d.get("total_sessions") or 0)
    if sessions >= 2:
        parts.append(f"returned {sessions}×")

    # What they looked at — a hot page beats a raw page count.
    pages = d.get("pages_visited") or []
    hot = _hot_page(pages)
    if hot:
        parts.append(f"viewed your {hot} page")
    elif len(pages) >= 3:
        parts.append(f"viewed {len(pages)} pages")

    # Attention depth.
    if int(d.get("max_scroll_depth") or 0) >= 75 or float(
        d.get("avg_time_on_page") or 0
    ) > 60:
        parts.append("read deeply")

    score = int(d.get("intent_score") or 0)

    # Nothing behavioural and not even high intent → no story worth telling.
    if not parts and score < HIGH_INTENT:
        return None

    head = parts[:3]
    head.append(f"intent {score}")
    return " · ".join(head)
