"""Phase 05 step 5b — dual-write of encrypted PII via SQLAlchemy mapper events.

On every ORM insert/update of a PII-bearing row, derive the *_ciphertext (and
*_bidx blind index) columns from the plaintext columns. This keeps the new
encrypted columns in sync WITHOUT touching the ~15 scattered write sites.

Reads still use the plaintext columns — this step only POPULATES the new
columns so 5c (backfill) and 5d (read cutover) have data to switch to. Rollback
is safe: the plaintext columns remain the source of truth.

Core-table inserts (pg_insert ... .values()) bypass mapper events, so those two
sites — visitor_emails upsert (events.py) and the beam identity graph upsert
(identity_resolver.py) — set the columns explicitly instead.

Registered once via register_pii_encryption_hooks(), called from main.py at
import time (and from the test app import).
"""

import structlog
from sqlalchemy import event

from apps.api.models.beam_identity import BeamIdentityNode
from apps.api.models.enrichment import EnrichmentProfile
from apps.api.models.visitor import IdentifiedVisitor
from apps.api.models.visitor_email import VisitorEmail
from apps.api.services.pii_crypto import email_hash, encrypt_pii

logger = structlog.get_logger()

_REGISTERED = False


def _sync_identity_pii(mapper, connection, target) -> None:
    """IdentifiedVisitor / BeamIdentityNode: encrypt email (+ blind index) + name."""
    target.email_ciphertext = encrypt_pii(target.email)
    target.email_bidx = email_hash(target.email) if target.email else None
    target.full_name_ciphertext = encrypt_pii(target.full_name)


def _sync_visitor_email_pii(mapper, connection, target) -> None:
    target.email_ciphertext = encrypt_pii(target.email)
    target.email_bidx = email_hash(target.email) if target.email else None


def _sync_enrichment_pii(mapper, connection, target) -> None:
    target.linkedin_url_ciphertext = encrypt_pii(target.linkedin_url)
    target.twitter_handle_ciphertext = encrypt_pii(target.twitter_handle)
    target.facebook_url_ciphertext = encrypt_pii(target.facebook_url)
    target.github_url_ciphertext = encrypt_pii(target.github_url)


def register_pii_encryption_hooks() -> None:
    """Idempotently register the before_insert/before_update listeners."""
    global _REGISTERED
    if _REGISTERED:
        return
    for model in (IdentifiedVisitor, BeamIdentityNode):
        event.listen(model, "before_insert", _sync_identity_pii)
        event.listen(model, "before_update", _sync_identity_pii)
    event.listen(VisitorEmail, "before_insert", _sync_visitor_email_pii)
    event.listen(VisitorEmail, "before_update", _sync_visitor_email_pii)
    event.listen(EnrichmentProfile, "before_insert", _sync_enrichment_pii)
    event.listen(EnrichmentProfile, "before_update", _sync_enrichment_pii)
    _REGISTERED = True
    logger.info("pii_encryption_hooks_registered")
