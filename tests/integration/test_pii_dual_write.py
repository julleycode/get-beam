"""Phase 05 step 5b integration: dual-write of encrypted PII columns.

Against the test DB (requires local PostgreSQL via docker-compose). Verifies
that every write path populates the *_ciphertext (+ *_bidx) columns while the
plaintext columns stay intact (reads still use them):

- ORM writes (IdentifiedVisitor, EnrichmentProfile, VisitorEmail) via mapper hooks
- Core upserts (beam identity graph, visitor_emails ingest) via explicit code

Hooks are registered when apps.api.main is imported (conftest does this).
"""

import uuid as uuidlib
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from apps.api.services.pii_crypto import decrypt_pii, email_hash

pytestmark = pytest.mark.integration


class TestOrmDualWrite:
    @pytest.mark.asyncio
    async def test_identified_visitor(self, test_db):
        from apps.api.models.visitor import IdentifiedVisitor

        sid = f"s_{uuidlib.uuid4().hex[:8]}"
        vid = f"v_{uuidlib.uuid4().hex[:8]}"
        email = "Lead@Acme.com"
        test_db.add(IdentifiedVisitor(site_id=sid, visitor_id=vid, email=email, full_name="Ann Lee"))
        await test_db.commit()

        row = (await test_db.execute(
            select(IdentifiedVisitor).where(IdentifiedVisitor.site_id == sid)
        )).scalar_one()

        assert row.email == email                       # plaintext untouched (reads still use it)
        assert row.email_ciphertext is not None
        assert decrypt_pii(row.email_ciphertext) == email
        assert row.email_bidx == email_hash(email)
        assert decrypt_pii(row.full_name_ciphertext) == "Ann Lee"

    @pytest.mark.asyncio
    async def test_enrichment_profile(self, test_db):
        from apps.api.models.enrichment import EnrichmentProfile

        sid = f"s_{uuidlib.uuid4().hex[:8]}"
        vid = f"v_{uuidlib.uuid4().hex[:8]}"
        test_db.add(EnrichmentProfile(
            site_id=sid, visitor_id=vid,
            linkedin_url="https://linkedin.com/in/ann",
            twitter_handle="annlee",
            github_url="https://github.com/ann",
        ))
        await test_db.commit()

        row = (await test_db.execute(
            select(EnrichmentProfile).where(EnrichmentProfile.site_id == sid)
        )).scalar_one()
        assert decrypt_pii(row.linkedin_url_ciphertext) == "https://linkedin.com/in/ann"
        assert decrypt_pii(row.twitter_handle_ciphertext) == "annlee"
        assert decrypt_pii(row.github_url_ciphertext) == "https://github.com/ann"
        assert row.facebook_url_ciphertext is None  # None plaintext → None ciphertext

    @pytest.mark.asyncio
    async def test_visitor_email_orm(self, test_db):
        from apps.api.models.visitor_email import VisitorEmail

        sid = f"s_{uuidlib.uuid4().hex[:8]}"
        vid = f"v_{uuidlib.uuid4().hex[:8]}"
        test_db.add(VisitorEmail(site_id=sid, visitor_id=vid, email="x@y.com", source="form"))
        await test_db.commit()

        row = (await test_db.execute(
            select(VisitorEmail).where(VisitorEmail.site_id == sid)
        )).scalar_one()
        assert decrypt_pii(row.email_ciphertext) == "x@y.com"
        assert row.email_bidx == email_hash("x@y.com")

    @pytest.mark.asyncio
    async def test_update_resyncs_ciphertext(self, test_db):
        from apps.api.models.visitor import IdentifiedVisitor

        sid = f"s_{uuidlib.uuid4().hex[:8]}"
        vid = f"v_{uuidlib.uuid4().hex[:8]}"
        obj = IdentifiedVisitor(site_id=sid, visitor_id=vid, email="old@y.com")
        test_db.add(obj)
        await test_db.commit()

        obj.email = "new@y.com"  # before_update hook must re-encrypt
        await test_db.commit()

        row = (await test_db.execute(
            select(IdentifiedVisitor).where(IdentifiedVisitor.site_id == sid)
        )).scalar_one()
        assert decrypt_pii(row.email_ciphertext) == "new@y.com"
        assert row.email_bidx == email_hash("new@y.com")


class TestCoreUpsertDualWrite:
    @pytest.mark.asyncio
    async def test_beam_identity_graph(self, test_db):
        from apps.api.models.beam_identity import BeamIdentityNode
        from apps.api.services.identity_resolver import IdentityResolver

        fp = f"fp2_{uuidlib.uuid4().hex}"
        visitor = SimpleNamespace(fingerprint=fp, site_id=f"s_{uuidlib.uuid4().hex[:8]}")
        resolver = IdentityResolver(db=test_db, redis_client=MagicMock())

        await resolver._upsert_beam_identity(
            visitor, {"email": "beam@y.com", "full_name": "Beam P", "confidence_score": 0.9}, "test"
        )

        row = (await test_db.execute(
            select(BeamIdentityNode).where(BeamIdentityNode.fingerprint == fp)
        )).scalar_one()
        assert decrypt_pii(row.email_ciphertext) == "beam@y.com"
        assert row.email_bidx == email_hash("beam@y.com")
        assert decrypt_pii(row.full_name_ciphertext) == "Beam P"

    @pytest.mark.asyncio
    async def test_visitor_email_ingest_path(self, test_client, test_db, monkeypatch):
        from apps.api.models.site import Site
        from apps.api.models.user import User
        from apps.api.models.visitor_email import VisitorEmail

        # Bypass the MX network lookup in the ingest path.
        async def _ok(email):
            return True, ""
        monkeypatch.setattr("apps.api.services.email_validator.validate_email", _ok)

        user = User(email=f"dw-{uuidlib.uuid4().hex[:8]}@test.com", full_name="DW")
        test_db.add(user)
        await test_db.flush()
        sid = f"s_{uuidlib.uuid4().hex[:8]}"
        vid = f"v_{uuidlib.uuid4().hex[:8]}"
        test_db.add(Site(site_id=sid, user_id=user.id, name="S", url="https://s.example.com"))
        await test_db.commit()

        resp = await test_client.post(
            "/api/v1/events/ingest",
            json={
                "site_id": sid,
                "visitor_id": vid,
                "events": [{
                    "type": "form_email_capture",
                    "email": "form@y.com",
                    "ts": datetime.utcnow().isoformat(),
                }],
            },
            headers={"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/120 Safari/537.36"},
        )
        assert resp.status_code == 204, resp.text

        row = (await test_db.execute(
            select(VisitorEmail).where(VisitorEmail.site_id == sid, VisitorEmail.visitor_id == vid)
        )).scalar_one()
        assert row.email == "form@y.com"
        assert decrypt_pii(row.email_ciphertext) == "form@y.com"
        assert row.email_bidx == email_hash("form@y.com")
