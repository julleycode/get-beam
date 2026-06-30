"""P5 (own-data): exclude known-contacts from net-new targeting exports.

The known-contacts list (the customer's CRM, stored hash-only) was a display-only
badge. P5 lets the owner actually drop those people from a net-new export/push:
_get_segment_visitors(exclude_known=True) filters out any contact whose email is
in the site's known_contacts — hash-vs-hash, never reversing the hash.
"""
import uuid as uuidlib

import pytest
import pytest_asyncio
from sqlalchemy import select

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def export_setup(test_db):
    from apps.api.models.segment import Segment, SegmentMember
    from apps.api.models.site import Site
    from apps.api.models.user import User
    from apps.api.models.visitor import IdentifiedVisitor
    from apps.api.models.known_contact import KnownContact
    from apps.api.services.known_hash import email_hash

    user = User(email=f"exp-{uuidlib.uuid4().hex[:8]}@test.com", full_name="Exp")
    test_db.add(user)
    await test_db.flush()

    site_id = f"exp_site_{uuidlib.uuid4().hex[:8]}"
    test_db.add(Site(site_id=site_id, user_id=user.id, name="Exp Site", url="https://exp.example.com"))

    seg_id = uuidlib.uuid4()
    test_db.add(Segment(id=seg_id, site_id=site_id, name="Audience", visitor_count=2))

    # Two emailable, non-suppressed identified visitors.
    for vid, em in [("v-known", "existing@acme.com"), ("v-new", "netnew@acme.com")]:
        test_db.add(SegmentMember(segment_id=seg_id, visitor_id=vid, site_id=site_id))
        test_db.add(IdentifiedVisitor(
            site_id=site_id, visitor_id=vid, email=em,
            full_name="A B", resolution_provider="form_capture", confidence_score=0.9,
        ))

    # The owner already has the first contact in their CRM (known-contacts list).
    test_db.add(KnownContact(site_id=site_id, email_hash=email_hash("existing@acme.com"), source="csv"))
    await test_db.commit()
    return {"site_id": site_id, "segment_id": str(seg_id)}


class TestExcludeKnownFromExport:
    @pytest.mark.asyncio
    async def test_default_includes_everyone(self, test_db, export_setup):
        from apps.api.services.csv_exporter import _get_segment_visitors

        rows = await _get_segment_visitors(test_db, export_setup["segment_id"])
        emails = {r["email"] for r in rows}
        assert emails == {"existing@acme.com", "netnew@acme.com"}

    @pytest.mark.asyncio
    async def test_exclude_known_drops_crm_contacts(self, test_db, export_setup):
        from apps.api.services.csv_exporter import _get_segment_visitors

        rows = await _get_segment_visitors(
            test_db, export_setup["segment_id"], exclude_known=True
        )
        emails = {r["email"] for r in rows}
        # The CRM contact is dropped; only the net-new lead remains.
        assert emails == {"netnew@acme.com"}
