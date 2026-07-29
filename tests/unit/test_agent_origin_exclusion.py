"""Phase 07 — Outreach-exclusion guardrail (SPEC AC10, highest-priority test).

An agent-classified record (one carrying a ``source_agent_visit_id`` marker) can
NEVER be selected as an email / social / export outreach target — directly or
indirectly — regardless of its ``resolution_provider``. Agents are never emailed;
only human/company contacts reached through the existing consent/suppression/
approval gates may be contacted.

Two layers of proof, all Fully-Automated (no Docker, no live DB):
  * C1/C2 — the guard function itself (`is_emailable_identity`).
  * C3     — each of the 3 real send/export entry points, exercised via a mocked
             `AsyncSession` (the same no-DB pattern Phase 4 used), proving the
             agent-origin record is excluded at every call site, not just the
             primary one.
  * C5     — a literal-field-name tripwire: `"source_agent_visit_id"` must appear
             in the guard file and all 3 call-site files, so a future rename
             fails loudly instead of silently reopening the outreach hole.

Non-vacuity (C4): against the pre-Phase-07 code, `is_emailable_identity` accepted
exactly one positional arg, so the 2-arg calls below raised `TypeError` — the C1
test was genuinely red before the guard override existed. Removing the
`if source_agent_visit_id is not None: return False` override in
`identity_classification.py` makes `test_agent_origin_overrides_person_level` fail
red for every person-level provider. Verified by reasoning + the PVL-confirmed
`TypeError` (per plan C4 note E3 — the line is not physically deleted/restored).
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import apps.api.main  # noqa: F401 — registers ALL ORM models so a REAL
#                        IdentifiedVisitor can be constructed (mapper config needs
#                        every related model, e.g. User→Draft, imported first).
from apps.api.models.visitor import IdentifiedVisitor
from apps.api.services.identity_classification import (
    COMPANY_LEVEL_PROVIDERS,
    PERSON_LEVEL_PROVIDERS,
    is_emailable_identity,
)
from apps.api.services.identity_resolver import IdentityResolver

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# C1/C2 — the guard function itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider", sorted(PERSON_LEVEL_PROVIDERS))
def test_agent_origin_overrides_person_level(provider):
    # Baseline: a person-level provider with no agent marker stays emailable.
    assert is_emailable_identity(provider) is True
    # AC10 override: the SAME person-level provider becomes non-emailable the
    # instant an agent-origin marker is present. The override fires first and
    # unconditionally, for EVERY person-level provider.
    assert is_emailable_identity(provider, source_agent_visit_id="fake-uuid") is False


def test_non_agent_identity_unaffected():
    # rb2b is a real person-level provider → emailable when no marker is passed.
    assert is_emailable_identity("rb2b", None) is True
    # hunter is a real company-level provider → never emailable (unchanged).
    assert is_emailable_identity("hunter", None) is False
    # Sanity: the two providers used above are the real classifications.
    assert "rb2b" in PERSON_LEVEL_PROVIDERS
    assert "hunter" in COMPANY_LEVEL_PROVIDERS


# ---------------------------------------------------------------------------
# C3 — site-level exclusion at each of the 3 real entry points
# ---------------------------------------------------------------------------


def _agent_origin_iv(provider="rb2b"):
    """A minimal IdentifiedVisitor-shaped mock that is agent-origin.

    provider defaults to a PERSON_LEVEL provider on purpose: absent the AC10
    override this record WOULD be emailable, so exclusion proves the guard —
    not merely the pre-existing company-level filter — is doing the work.
    """
    iv = MagicMock()
    iv.resolution_provider = provider
    iv.source_agent_visit_id = "agent-visit-123"
    iv.email = "person@example.com"
    iv.do_not_email = False
    return iv


async def test_campaign_sender_excludes_agent_origin(monkeypatch):
    from apps.api.services import campaign_sender

    # Never actually construct/send; the record must be skipped before either.
    monkeypatch.setattr(campaign_sender, "EmailSender", MagicMock())
    monkeypatch.setattr(
        campaign_sender, "resolve_sender_for_site", AsyncMock(return_value=None)
    )

    member_result = MagicMock()
    member_result.all.return_value = [("vid-1",)]
    site_result = MagicMock()
    site_result.first.return_value = ("https://site.example", "Site", "Owner", "o@e.com")
    iv_result = MagicMock()
    iv_result.scalar_one_or_none.return_value = _agent_origin_iv()

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[member_result, site_result, iv_result])

    campaign = MagicMock()
    campaign.plan = {
        "touchpoints": [{"channel": "email", "subject": "s", "body": "b", "step": 1}]
    }
    campaign.segment_id = "seg-1"
    campaign.site_id = "site-1"

    summary = await campaign_sender.send_campaign_emails(db, campaign)

    # Excluded at the guard: nothing sent, the skip counter incremented.
    assert summary["sent"] == 0
    assert summary["skipped_company_level"] == 1


async def test_resolve_linkedin_targets_excludes_agent_origin():
    from apps.api.routers import campaigns

    member_result = MagicMock()
    member_result.all.return_value = [("vid-1",)]
    iv_result = MagicMock()
    iv_result.scalar_one_or_none.return_value = _agent_origin_iv()

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[member_result, iv_result])

    campaign = MagicMock()
    campaign.segment_id = "seg-1"

    urls, skipped = await campaigns._resolve_linkedin_targets(
        db, "site-1", campaign, limit=10
    )

    # Excluded at the guard: no LinkedIn target collected, skip counted.
    assert urls == []
    assert skipped == 1


async def test_csv_exporter_excludes_agent_origin():
    from apps.api.services import csv_exporter

    member = MagicMock()
    member.site_id = "site-1"
    member.visitor_id = "vid-1"
    members_result = MagicMock()
    members_result.scalars.return_value.all.return_value = [member]

    iv_result = MagicMock()
    iv_result.scalar_one_or_none.return_value = _agent_origin_iv()

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[members_result, iv_result])

    visitors = await csv_exporter._get_segment_visitors(db, "seg-1", exclude_known=False)

    # Excluded at the guard: the agent-origin record never reaches the export list.
    assert visitors == []


# ---------------------------------------------------------------------------
# Phase 05 D5/D6 (BINDING) — AC10 override holds against a REAL row created by
# the actual company-resolution INSERT path (not a hand-built mock). This drives
# the real IdentityResolver._save_identified with the agent-origin marker set —
# the same code the Phase 05 sweep uses — and proves the persisted row it builds
# is non-emailable even for a PERSON_LEVEL provider.
# ---------------------------------------------------------------------------


async def test_ac10_real_sweep_created_row_is_non_emailable():
    added: list = []

    db = MagicMock()
    db.add = lambda o: added.append(o)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock())

    resolver = IdentityResolver(db, redis_client=None)
    # The sweep sets this before calling _save_identified (GUARD #1, atomic).
    resolver._active_source_agent_visit_id = "real-agent-visit-id"

    visitor = SimpleNamespace(
        visitor_id="agent:real-agent-visit-id", site_id="site-1", fingerprint=None
    )
    # rb2b is PERSON_LEVEL — absent the marker this WOULD be emailable, so the
    # exclusion proves the AC10 marker override, not the company-level filter.
    row = await resolver._save_identified(visitor, {"full_name": "Jane"}, "rb2b")

    assert isinstance(row, IdentifiedVisitor)
    assert row is added[0]
    # The REAL row carries the marker written at INSERT time …
    assert row.source_agent_visit_id == "real-agent-visit-id"
    # … and is therefore NEVER an outreach target (SPEC AC10 / Phase 7 guard).
    assert is_emailable_identity(row.resolution_provider, row.source_agent_visit_id) is False


# ---------------------------------------------------------------------------
# C5 — literal-field-name tripwire (STRIDE tampering guard)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]

_GUARDED_FILES = [
    "apps/api/services/identity_classification.py",
    "apps/api/services/campaign_sender.py",
    "apps/api/routers/campaigns.py",
    "apps/api/services/csv_exporter.py",
]


@pytest.mark.parametrize("rel_path", _GUARDED_FILES)
def test_source_agent_visit_id_literal_field_name_tripwire(rel_path):
    # Pure text search — no imports, cannot be broken by mocking. If any future
    # change renames the field in one file without updating the others, this
    # fails loudly instead of silently reopening the AC10 outreach hole.
    text = (_REPO_ROOT / rel_path).read_text(encoding="utf-8")
    assert "source_agent_visit_id" in text, (
        f"{rel_path} is missing the literal field name 'source_agent_visit_id' — "
        "a rename here silently disables the AC10 agent-origin outreach guard."
    )
