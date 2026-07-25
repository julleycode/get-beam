"""AC5 — hash-only egress.

The outbound payload builder in services/ads_push.py must never carry a
plaintext identifier. Pure unit test: no DB, no network.
"""

import re
from dataclasses import asdict

import pytest

from apps.api.services.ads_push import build_hashed_contacts
from apps.api.services.csv_exporter import _sha256

pytestmark = pytest.mark.unit

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

_ROWS = [
    {
        "email": "Ada.Lovelace@Example.COM",
        "first_name": "Ada",
        "last_name": "Lovelace",
        "phone": "+15551234567",
        "city": "London",
        "region": "England",
        "country": "GB",
    },
    {
        "email": "grace@navy.example.org",
        "first_name": "Grace",
        "last_name": "",
        "phone": "",
        "city": "",
        "region": "",
        "country": "US",
    },
]


def test_ads_hash_payload_never_contains_plaintext_email():
    contacts = build_hashed_contacts(_ROWS)
    blob = repr([asdict(c) for c in contacts])

    assert "@" not in blob, "payload leaked an @ — plaintext identifier present"
    assert not _EMAIL_RE.search(blob), "payload matched an email regex"
    for row in _ROWS:
        assert row["email"] not in blob
        assert row["email"].lower() not in blob


def test_ads_hash_uses_the_same_digest_as_the_csv_export():
    # Same people must land in the same platform buckets whether they arrive
    # via CSV export or via the API push.
    contacts = build_hashed_contacts(_ROWS)
    assert contacts[0].email_sha256 == _sha256("Ada.Lovelace@Example.COM")
    assert contacts[0].phone_sha256 == _sha256("+15551234567")
    assert contacts[0].country_sha256 == _sha256("GB")


def test_ads_hash_leaves_empty_fields_empty_not_hashed():
    # Hashing "" would give every contact the same constant digest, which a
    # platform could match on. Empty stays empty.
    contacts = build_hashed_contacts(_ROWS)
    assert contacts[1].last_name_sha256 == ""
    assert contacts[1].phone_sha256 == ""
    assert contacts[1].city_sha256 == ""


def test_ads_hash_skips_rows_without_an_email():
    contacts = build_hashed_contacts([{"email": "", "first_name": "Nobody"}])
    assert contacts == []
