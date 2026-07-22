"""Phase 1 unit tests — PII ciphertext backfill (no DB).

Exercises the pure per-row transform (`compute_row_updates`) that the DB
batching wraps. Proves: correct encrypt + blind-index population, idempotency
(already-populated rows are skipped), and that enrichment social handles get
ciphertext but NO blind index. No database required.
"""

from apps.api.scripts.backfill_pii_ciphertext import (
    TABLE_CONFIGS,
    compute_row_updates,
)
from apps.api.services import pii_crypto

VISITOR_EMAILS = TABLE_CONFIGS["visitor_emails"].fields
IDENTIFIED = TABLE_CONFIGS["identified_visitors"].fields
ENRICHMENT = TABLE_CONFIGS["enrichment_profiles"].fields


class TestEncryptsPlaintextRow:
    def test_should_encrypt_a_plaintext_only_row_and_populate_matching_bidx(self):
        row = {"email": "lead@acme.com", "email_ciphertext": None, "email_bidx": None}
        updates = compute_row_updates(VISITOR_EMAILS, row)

        # ciphertext decrypts back to the original plaintext
        assert "email_ciphertext" in updates
        assert pii_crypto.decrypt_pii(updates["email_ciphertext"]) == "lead@acme.com"
        # bidx == the canonical blind index for that email
        assert updates["email_bidx"] == pii_crypto.email_hash("lead@acme.com")

    def test_should_populate_full_name_ciphertext_without_a_bidx(self):
        row = {
            "email": None,
            "email_ciphertext": None,
            "email_bidx": None,
            "full_name": "Ada Lovelace",
            "full_name_ciphertext": None,
        }
        updates = compute_row_updates(IDENTIFIED, row)

        assert "full_name_ciphertext" in updates
        assert pii_crypto.decrypt_pii(updates["full_name_ciphertext"]) == "Ada Lovelace"
        # full_name has no blind index
        assert "full_name_bidx" not in updates

    def test_should_skip_fields_whose_plaintext_is_empty(self):
        row = {"email": None, "email_ciphertext": None, "email_bidx": None}
        assert compute_row_updates(VISITOR_EMAILS, row) == {}


class TestIdempotency:
    def test_should_skip_a_row_that_already_has_ciphertext_populated(self):
        existing_ct = pii_crypto.encrypt_pii("lead@acme.com")
        existing_bidx = pii_crypto.email_hash("lead@acme.com")
        row = {
            "email": "lead@acme.com",
            "email_ciphertext": existing_ct,
            "email_bidx": existing_bidx,
        }
        # Nothing to do — fully backfilled row yields no updates (no double-encrypt).
        assert compute_row_updates(VISITOR_EMAILS, row) == {}

    def test_should_only_fill_the_missing_bidx_when_ciphertext_present(self):
        existing_ct = pii_crypto.encrypt_pii("lead@acme.com")
        row = {
            "email": "lead@acme.com",
            "email_ciphertext": existing_ct,
            "email_bidx": None,
        }
        updates = compute_row_updates(VISITOR_EMAILS, row)

        # ciphertext untouched (not re-encrypted), only bidx backfilled
        assert "email_ciphertext" not in updates
        assert updates["email_bidx"] == pii_crypto.email_hash("lead@acme.com")


class TestEnrichmentHandles:
    def test_should_encrypt_social_handles_with_no_bidx(self):
        row = {
            "linkedin_url": "https://linkedin.com/in/ada",
            "linkedin_url_ciphertext": None,
            "twitter_handle": "@ada",
            "twitter_handle_ciphertext": None,
            "facebook_url": None,
            "facebook_url_ciphertext": None,
            "github_url": None,
            "github_url_ciphertext": None,
        }
        updates = compute_row_updates(ENRICHMENT, row)

        assert (
            pii_crypto.decrypt_pii(updates["linkedin_url_ciphertext"])
            == "https://linkedin.com/in/ada"
        )
        assert pii_crypto.decrypt_pii(updates["twitter_handle_ciphertext"]) == "@ada"
        # NO blind-index columns are written for enrichment handles
        assert not any(key.endswith("_bidx") for key in updates)
        # empty handles contribute nothing
        assert "facebook_url_ciphertext" not in updates
        assert "github_url_ciphertext" not in updates

    def test_enrichment_config_declares_no_bidx_fields(self):
        # Structural guard: enrichment_profiles is ciphertext-only by design.
        assert all(spec.bidx is None for spec in ENRICHMENT)
