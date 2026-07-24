"""Phase 2 (PII-at-rest) unit tests — known_hash / pii_crypto unification.

Pins the invariant that ``known_hash.email_hash`` and ``pii_crypto.email_hash``
produce identical output. After Phase 2, ``known_hash.email_hash`` delegates to
``pii_crypto.email_hash``; this test guards against any future re-divergence
(e.g. a reverted delegation, or a copy-paste of the old standalone impl).

Inputs deliberately include mixed-case and leading/trailing-whitespace variants
to prove both route through the same ``normalize_email`` before hashing.
"""

import pytest

from apps.api.services import known_hash, pii_crypto

# Fixed input set: plain, mixed-case, leading/trailing whitespace, mixed both,
# and an all-caps variant. 5+ inputs incl. case/whitespace per the plan.
EQUALITY_INPUTS = [
    "lead@acme.com",
    "Lead@Acme.com",
    "  lead@acme.com  ",
    "\tLEAD@ACME.COM\n",
    "USER.Name+tag@Example.CO",
    " mixed@Example.com ",
]


class TestBlindIndexUnification:
    @pytest.mark.parametrize("email", EQUALITY_INPUTS)
    def test_known_hash_equals_pii_crypto(self, email):
        assert known_hash.email_hash(email) == pii_crypto.email_hash(email)

    def test_case_and_whitespace_variants_collapse_to_same_hash(self):
        # All variants of the same address (case/whitespace) must produce one
        # hash — proves both impls share the same normalize_email step.
        variants = ["lead@acme.com", "Lead@Acme.com", "  LEAD@acme.com  ", "\tlead@acme.com\n"]
        hashes = {known_hash.email_hash(v) for v in variants}
        assert len(hashes) == 1
        # ...and that single hash matches pii_crypto's for the canonical form.
        assert hashes == {pii_crypto.email_hash("lead@acme.com")}

    def test_distinct_emails_produce_distinct_hashes(self):
        assert known_hash.email_hash("a@b.com") != known_hash.email_hash("c@d.com")

    def test_hash_shape_is_sha256_hex(self):
        digest = known_hash.email_hash("lead@acme.com")
        assert isinstance(digest, str) and len(digest) == 64


class TestNormalizeEmailPreserved:
    """normalize_email is still imported by known_contacts.py — keep it public."""

    def test_normalize_email_still_exported(self):
        assert known_hash.normalize_email("  Lead@Acme.com  ") == "lead@acme.com"
