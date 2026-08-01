"""Handoff Detection H2 — AC-H2-3 emailability separation (PROGRAM HARD GATE).

The single highest-priority gate in the Handoff Detection program (mirrors
EvalLayer's AC10 discipline). A fetch↔click handoff link is pure attribution
metadata on a structurally separate table. It must NEVER, in either direction:
  (a) change a linked HUMAN visitor's emailable status, or
  (b) make the agent-fetch side of the link an outreach target.

Proven three ways, all Fully-Automated (no Docker, no live DB):
  * Direction (a): a REAL IdentifiedVisitor + a REAL AgentHandoffLink for the same
    visitor_id — ``is_emailable_identity`` is computed identically with or without
    the link, because it never reads ``agent_handoff_links`` at all.
  * Direction (b): the ``AgentHandoffLink`` model has NO ``source_agent_visit_id``
    column and no path into IdentifiedVisitor — structurally impossible to make an
    agent-fetch record emailable.
  * Tripwire (C5-style): ``source_agent_visit_id`` must be ABSENT from the new H2
    files, so a future edit can't quietly wire the emailability marker into them.

E-C4 non-vacuity: the assertions use a REAL constructed IdentifiedVisitor +
AgentHandoffLink pair (not pure mocks), mirroring Phase 7's
``test_ac10_real_sweep_created_row_is_non_emailable`` discipline.
"""

import uuid
from pathlib import Path

import pytest

import apps.api.main  # noqa: F401 — registers ALL ORM models so REAL rows can be
#                        constructed (mapper config needs every related model).
from apps.api.models.agent_handoff_link import AgentHandoffLink
from apps.api.models.visitor import IdentifiedVisitor
from apps.api.services.identity_classification import (
    PERSON_LEVEL_PROVIDERS,
    is_emailable_identity,
)

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _real_handoff_link(visitor_id="vid-1", site_id="site-1"):
    """A REAL AgentHandoffLink ORM row (not a mock)."""
    return AgentHandoffLink(
        site_id=site_id,
        visitor_id=visitor_id,
        agent_fetch_event_id=uuid.uuid4(),
        confidence="high",
        method="temporal-page-match",
        delta_seconds=60,
        matched_page="/pricing",
    )


# --- Direction (a): a linked human's emailability is unchanged ---------------


def test_linked_human_emailability_unchanged_both_ways():
    provider = sorted(PERSON_LEVEL_PROVIDERS)[0]

    # A REAL person-level identity with NO agent-origin marker → emailable.
    iv = IdentifiedVisitor(
        site_id="site-1",
        visitor_id="vid-1",
        resolution_provider=provider,
        email="person@example.com",
    )
    baseline = is_emailable_identity(iv.resolution_provider, iv.source_agent_visit_id)
    assert baseline is True

    # A REAL handoff link now exists for the SAME visitor. Emailability is computed
    # from (provider, source_agent_visit_id) ONLY — the link is invisible to it, so
    # the result is byte-for-byte identical. The link changed nothing.
    _link = _real_handoff_link(visitor_id="vid-1")
    after = is_emailable_identity(iv.resolution_provider, iv.source_agent_visit_id)
    assert after is baseline is True
    # The human still carries no agent-origin marker (the link did not add one).
    assert iv.source_agent_visit_id is None


# --- Direction (b): the agent-fetch side can never become emailable ----------


def test_handoff_link_has_no_emailability_marker_column():
    # Structural proof: the table simply has no source_agent_visit_id column.
    columns = {c.name for c in AgentHandoffLink.__table__.columns}
    assert "source_agent_visit_id" not in columns
    # And the expected additive columns ARE present.
    assert {"site_id", "visitor_id", "agent_fetch_event_id", "confidence"} <= columns


def test_real_handoff_link_instance_exposes_no_marker():
    link = _real_handoff_link()
    # A constructed row has no marker attribute set to anything meaningful.
    assert getattr(link, "source_agent_visit_id", None) is None


# --- Tripwire (C5-style literal-field-name absence) --------------------------

_H2_FILES = [
    "apps/api/models/agent_handoff_link.py",
    "apps/api/services/agent_handoff_correlation.py",
]


@pytest.mark.parametrize("rel_path", _H2_FILES)
def test_source_agent_visit_id_absent_from_h2_files(rel_path):
    # Pure text search — the emailability marker must NEVER appear in the H2
    # correlation surface. If a future edit wires it in, this fails loudly instead
    # of silently coupling handoff links to the outreach-exclusion mechanism.
    text = (_REPO_ROOT / rel_path).read_text(encoding="utf-8")
    assert "source_agent_visit_id" not in text, (
        f"{rel_path} references 'source_agent_visit_id' — the H2 handoff surface "
        "must stay structurally separate from the AC-H2-3 emailability guardrail."
    )
    assert "is_emailable_identity" not in text, (
        f"{rel_path} references 'is_emailable_identity' — the H2 handoff surface "
        "must never call the emailability guard."
    )
