"""Own-data P7b: known-contact routing — skip paid enrichment when the resolved
email is already in the customer's uploaded CRM list (they own that data)."""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.services import known_contacts_match as kcm
from apps.api.services.enricher import Enricher


def _result(scalar=None, rows=None):
    r = MagicMock()
    r.scalar_one_or_none = MagicMock(return_value=scalar)
    if rows is not None:
        r.__iter__ = lambda self: iter(rows)
    return r


class TestKnownContactHelper:
    @pytest.mark.asyncio
    async def test_is_known_true_with_source(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(scalar="csv"))
        assert await kcm.is_known_contact(db, "site", "a@b.com") == (True, "csv")

    @pytest.mark.asyncio
    async def test_is_known_false_when_absent(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(scalar=None))
        assert await kcm.is_known_contact(db, "site", "a@b.com") == (False, None)

    @pytest.mark.asyncio
    async def test_is_known_empty_email_no_query(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        assert await kcm.is_known_contact(db, "site", "") == (False, None)
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_source_map(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result(rows=[("h1", "csv"), ("h2", "crm")]))
        out = await kcm.known_source_map(db, "site", {"h1", "h2", "h3"})
        assert out == {"h1": "csv", "h2": "crm"}

    @pytest.mark.asyncio
    async def test_source_map_empty_input_no_query(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        assert await kcm.known_source_map(db, "site", set()) == {}
        db.execute.assert_not_called()


def _visitor():
    return SimpleNamespace(
        site_id="site", visitor_id=f"v-{uuid.uuid4().hex[:8]}",
        enrichment_status="pending",
        first_seen=datetime.now(timezone.utc), last_seen=datetime.now(timezone.utc),
    )


class TestEnricherSkipsKnown:
    def _enricher(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        e = Enricher(db=db)
        # Return None so the waterfall ends right after the (asserted) PDL call —
        # we only care WHETHER the paid step was reached, not the full cascade.
        e._enrich_pdl = AsyncMock(return_value=None)
        return e

    @pytest.mark.asyncio
    async def test_skips_paid_enrichment_for_known_contact(self):
        e = self._enricher()
        visitor = _visitor()
        identified = SimpleNamespace(email="known@acme.com")
        with patch("apps.api.services.enricher.settings") as s, \
             patch("apps.api.services.known_contacts_match.is_known_contact",
                   AsyncMock(return_value=(True, "csv"))):
            s.skip_enrich_known = True
            result = await e.enrich_tier1(visitor, identified)
        assert result is None
        assert visitor.enrichment_status == "skipped_known"
        e._enrich_pdl.assert_not_called()  # no provider spend

    @pytest.mark.asyncio
    async def test_proceeds_when_not_known(self):
        e = self._enricher()
        visitor = _visitor()
        identified = SimpleNamespace(email="new@lead.com")
        with patch("apps.api.services.enricher.settings") as s, \
             patch("apps.api.services.known_contacts_match.is_known_contact",
                   AsyncMock(return_value=(False, None))):
            s.skip_enrich_known = True
            s.people_data_labs_api_key = "k"
            await e.enrich_tier1(visitor, identified)
        e._enrich_pdl.assert_awaited_once()  # reached the paid waterfall

    @pytest.mark.asyncio
    async def test_flag_off_always_enriches(self):
        e = self._enricher()
        visitor = _visitor()
        identified = SimpleNamespace(email="known@acme.com")
        with patch("apps.api.services.enricher.settings") as s, \
             patch("apps.api.services.known_contacts_match.is_known_contact",
                   AsyncMock(return_value=(True, "csv"))) as chk:
            s.skip_enrich_known = False
            s.people_data_labs_api_key = "k"
            await e.enrich_tier1(visitor, identified)
        chk.assert_not_called()  # gate off → don't even check known
        e._enrich_pdl.assert_awaited_once()
