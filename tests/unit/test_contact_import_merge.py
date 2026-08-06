"""Phase 4 C1/D6 — merge-on-click against a phantom imported contact.

Phase 4 writes NO new merge code. The unification is done by the email-dedup
branch already inside ``IdentityResolver._save_identified``: when a later real
visit resolves to an email that already belongs to another visitor on the same
site, the CLICK-DERIVED row is marked ``"merged"`` and its
``canonical_visitor_id`` points AT the existing row. Phase 4's only obligation
is that the phantom's ``IdentifiedVisitor.email`` be discoverable by that lookup.

These tests prove the branch actually fires for the phantom-row shape (rather
than assuming it "just works"), and — critically — assert the POINTER outcome,
not literal same-``visitor_id`` equality: the phantom keeps its own
``visitor_id``; the click-derived row points at it.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import apps.api.main  # noqa: F401 — configures the SQLAlchemy mapper registry

import pytest

from apps.api.models.visitor import IdentifiedVisitor
from apps.api.services.identity_resolver import IdentityResolver

PHANTOM_VISITOR_ID = "import:11111111-2222-3333-4444-555555555555"


def _resolver_with_phantom(monkeypatch, phantom: IdentifiedVisitor | None):
    """Resolver whose email-dedup lookup returns ``phantom`` (or nothing)."""
    added: list = []

    async def _exec(stmt, *a, **k):
        m = MagicMock()
        m.scalar_one_or_none.return_value = phantom
        m.scalars.return_value.all.return_value = []
        return m

    db = MagicMock()
    db.add = lambda o: added.append(o)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.execute = AsyncMock(side_effect=_exec)

    resolver = IdentityResolver(db, redis_client=None)
    # Email validation is a separate concern (network/MX); force it valid so this
    # test isolates the dedup branch.
    monkeypatch.setattr(
        "apps.api.services.email_validator.validate_email",
        AsyncMock(return_value=(True, None)),
    )
    return resolver, added


def _phantom_identity() -> IdentifiedVisitor:
    return IdentifiedVisitor(
        visitor_id=PHANTOM_VISITOR_ID,
        site_id="site-1",
        email="ada@example.com",  # lowercase-normalized, as the importer writes it
        full_name="Ada Lovelace",
        resolution_provider="contact_import",
    )


@pytest.mark.asyncio
async def test_real_visit_merges_onto_phantom_via_canonical_pointer(monkeypatch):
    resolver, added = _resolver_with_phantom(monkeypatch, _phantom_identity())

    click_visitor = SimpleNamespace(
        visitor_id="v-real-abc",
        site_id="site-1",
        fingerprint=None,
        identity_status="anonymous",
        canonical_visitor_id=None,
        is_abuse_flagged=False,
    )
    out = await resolver._save_identified(
        click_visitor, {"email": "Ada@Example.com"}, "form_capture"
    )

    # POINTER outcome — not literal same-visitor_id equality.
    assert click_visitor.identity_status == "merged"
    assert click_visitor.canonical_visitor_id == PHANTOM_VISITOR_ID
    assert click_visitor.visitor_id != PHANTOM_VISITOR_ID
    # The phantom's own row stays canonical, and no duplicate identity is inserted.
    assert out.visitor_id == PHANTOM_VISITOR_ID
    # (a cost-ledger row may also be added — only a duplicate IDENTITY is banned)
    assert not [o for o in added if isinstance(o, IdentifiedVisitor)]


@pytest.mark.asyncio
async def test_no_phantom_match_creates_an_ordinary_identity(monkeypatch):
    """Control: without a matching phantom the dedup branch must NOT fire."""
    resolver, added = _resolver_with_phantom(monkeypatch, None)

    visitor = SimpleNamespace(
        visitor_id="v-real-xyz",
        site_id="site-1",
        fingerprint=None,
        identity_status="anonymous",
        canonical_visitor_id=None,
        is_abuse_flagged=False,
    )
    await resolver._save_identified(visitor, {"email": "nobody@example.com"}, "form_capture")

    assert visitor.identity_status != "merged"
    assert visitor.canonical_visitor_id is None
    assert [
        o for o in added if isinstance(o, IdentifiedVisitor)
    ], "an IdentifiedVisitor row must be inserted when no phantom matches"


@pytest.mark.asyncio
async def test_match_key_is_exact_lowercase_email_only(monkeypatch):
    """C3: exact lowercase email is the ONLY match key in v1 (no fingerprint)."""
    resolver, _ = _resolver_with_phantom(monkeypatch, _phantom_identity())
    visitor = SimpleNamespace(
        visitor_id="v-real-def",
        site_id="site-1",
        fingerprint="same-device-fingerprint",
        identity_status="anonymous",
        canonical_visitor_id=None,
        is_abuse_flagged=False,
    )
    # Uppercase input still matches — the resolver lowercases before the lookup.
    await resolver._save_identified(visitor, {"email": "  ADA@EXAMPLE.COM "}, "form_capture")
    assert visitor.canonical_visitor_id == PHANTOM_VISITOR_ID
