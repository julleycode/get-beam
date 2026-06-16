"""Phase 05 step 5a unit tests — PII encryption helpers (no DB).

Round-trip, null handling, real encryption, and tolerant decryption of
non-ciphertext (the mixed-data window during rollout).
"""

import pytest

from apps.api.services.pii_crypto import decrypt_pii, encrypt_pii


class TestEncryptPii:
    def test_round_trip(self):
        ct = encrypt_pii("lead@acme.com")
        assert ct is not None
        assert decrypt_pii(ct) == "lead@acme.com"

    def test_ciphertext_differs_from_plaintext(self):
        ct = encrypt_pii("lead@acme.com")
        assert ct != "lead@acme.com"

    def test_ciphertext_is_non_deterministic(self):
        # Fernet embeds a random IV + timestamp → two encryptions differ, but
        # both decrypt back to the same plaintext. (This is why we need a
        # separate blind index for lookups.)
        a = encrypt_pii("lead@acme.com")
        b = encrypt_pii("lead@acme.com")
        assert a != b
        assert decrypt_pii(a) == decrypt_pii(b) == "lead@acme.com"

    @pytest.mark.parametrize("empty", [None, ""])
    def test_encrypt_empty_returns_none(self, empty):
        assert encrypt_pii(empty) is None

    def test_decrypt_none_returns_none(self):
        assert decrypt_pii(None) is None

    def test_decrypt_plaintext_is_tolerant(self):
        # A value that isn't valid Fernet ciphertext (pre-backfill plaintext)
        # is returned unchanged rather than raising.
        assert decrypt_pii("not-encrypted@acme.com") == "not-encrypted@acme.com"
