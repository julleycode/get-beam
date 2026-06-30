"""Changelog auto-generator tests (GitHub → Gemini → published entries).

GitHub fetch and Gemini are both mocked, so this runs offline. It exercises the
real classify/parse + dedup/publish wiring in services/changelog_generator.py.
"""

import json

import pytest

from apps.api.models.changelog_entry import ChangelogEntry
from apps.api.services import changelog_generator as gen
from sqlalchemy import select

pytestmark = pytest.mark.integration


_PRS = [
    {"number": 101, "title": "feat: per-browser capture breakdown", "body": "Shows Safari coverage", "merged_at": "2026-06-13T08:24:00Z"},
    {"number": 102, "title": "fix: stop sign-in redirect loop", "body": "Login was impossible", "merged_at": "2026-06-09T12:25:38Z"},
    {"number": 103, "title": "refactor: split identity_resolver god-file", "body": "Pure structural, no logic change", "merged_at": "2026-06-29T09:28:05Z"},
]


def _fake_gemini_factory():
    """Return a gemini_generate stub keyed off PR title content."""
    async def _fake(prompt: str, **kwargs) -> str:
        if "capture breakdown" in prompt:
            return json.dumps({"worthy": True, "category": "new", "title": "See what Safari hides", "body": "Estimate how many visitors Safari blocks from tracking."})
        if "redirect loop" in prompt:
            return json.dumps({"worthy": True, "category": "fixed", "title": "Reliable login", "body": "Signing in no longer bounces you back to the login page."})
        # refactor → internal
        return json.dumps({"worthy": False})
    return _fake


@pytest.fixture
def patch_sources(monkeypatch):
    async def _fake_fetch(limit: int = 30):
        return _PRS[:limit]
    monkeypatch.setattr(gen, "fetch_recent_merged_prs", _fake_fetch)
    monkeypatch.setattr(gen, "gemini_generate", _fake_gemini_factory())


@pytest.mark.asyncio
async def test_sync_imports_worthy_skips_internal(test_db, patch_sources) -> None:
    result = await gen.sync_from_github(test_db, limit=30)
    assert result.scanned == 3
    assert result.imported == 2          # capture + login
    assert result.skipped_internal == 1  # refactor
    assert result.already_present == 0

    rows = (
        await test_db.execute(
            select(ChangelogEntry).where(ChangelogEntry.source_ref.in_(["pr-101", "pr-102", "pr-103"]))
        )
    ).scalars().all()
    by_ref = {r.source_ref: r for r in rows}
    assert set(by_ref) == {"pr-101", "pr-102"}              # refactor not stored
    assert by_ref["pr-101"].status == "published"
    assert by_ref["pr-101"].category == "new"
    assert by_ref["pr-102"].category == "fixed"
    # published_at carried from the PR merge time → correct landing-page order.
    assert by_ref["pr-101"].published_at is not None


@pytest.mark.asyncio
async def test_sync_is_idempotent(test_db, patch_sources) -> None:
    first = await gen.sync_from_github(test_db, limit=30)
    assert first.imported == 2
    second = await gen.sync_from_github(test_db, limit=30)
    assert second.imported == 0           # nothing new
    assert second.already_present == 2    # the two imported PRs recognised
    assert second.skipped_internal == 1   # refactor re-skipped (not recorded)

    # No duplicates.
    count = len(
        (
            await test_db.execute(
                select(ChangelogEntry).where(ChangelogEntry.source_ref == "pr-101")
            )
        ).scalars().all()
    )
    assert count == 1


@pytest.mark.asyncio
async def test_missing_token_raises(test_db, monkeypatch) -> None:
    from apps.api.config import settings

    monkeypatch.setattr(settings, "github_token", "")
    with pytest.raises(gen.ChangelogSyncError):
        await gen.fetch_recent_merged_prs()


def test_parse_gemini_json_tolerates_fence() -> None:
    fenced = '```json\n{"worthy": true, "category": "new", "title": "x", "body": "y"}\n```'
    parsed = gen._parse_gemini_json(fenced)
    assert parsed and parsed["worthy"] is True


@pytest.mark.asyncio
async def test_classify_skips_on_bad_json(monkeypatch) -> None:
    async def _bad(prompt: str, **kwargs) -> str:
        return "not json at all"
    monkeypatch.setattr(gen, "gemini_generate", _bad)
    assert await gen.classify_and_rewrite("anything", "body") is None
