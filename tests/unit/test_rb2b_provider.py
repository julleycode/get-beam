"""Unit tests for RB2B business-profile parsing."""

from apps.api.services.identity_providers.rb2b import (
    _looks_like_plaintext_email,
    parse_rb2b_business_profile,
)


def test_rejects_md5_as_email():
    assert _looks_like_plaintext_email("eeefe37a523b32ff461ac14887639058") is False
    assert _looks_like_plaintext_email("janet@example.com") is True


def test_parse_hashed_emails_but_name_and_linkedin():
    """Live RB2B shape: HEM-only emails + first/last + linkedinurl."""
    person = {
        "personal_emails": [
            "eeefe37a523b32ff461ac14887639058",
            "3e9532110c07820a840540a4dba313e6",
        ],
        "work_email_confirmed": "e6665e2f510946cb7499abdf3e5b2f56",
        "first_name": "Janet",
        "last_name": "Valla",
        "linkedinurl": "https://www.linkedin.com/in/janet-valla-84460269",
        "current_company": "",
        "title": "",
        "country": "United States",
    }
    parsed = parse_rb2b_business_profile(person, hem_score="1.0")
    assert parsed is not None
    assert parsed["email"] is None
    assert parsed["full_name"] == "Janet Valla"
    assert parsed["linkedin_url"] == "https://www.linkedin.com/in/janet-valla-84460269"
    assert parsed["country"] == "US"
    assert parsed["confidence_score"] == 0.99


def test_parse_prefers_plaintext_work_email():
    person = {
        "work_email": "janet@acme.com",
        "personal_emails": ["eeefe37a523b32ff461ac14887639058"],
        "full_name": "Janet Valla",
        "linkedin_url": "https://www.linkedin.com/in/janet-valla",
    }
    parsed = parse_rb2b_business_profile(person, hem_score=0.8)
    assert parsed is not None
    assert parsed["email"] == "janet@acme.com"
    assert parsed["full_name"] == "Janet Valla"
    assert parsed["confidence_score"] == 0.8


def test_parse_identity_business_plaintext_work_email_confirmed():
    """Full Business Enrichment returns plaintext in work_email_confirmed."""
    person = {
        "work_email_confirmed": "danielle@sftoyota.com",
        "work_email_confirmed_md5": "e6665e2f510946cb7499abdf3e5b2f56",
        "first_name": "Janet",
        "last_name": "Valla",
        "linkedinurl": "https://www.linkedin.com/in/janet-valla-84460269",
        "country": "United States",
    }
    parsed = parse_rb2b_business_profile(person, hem_score="1.0")
    assert parsed is not None
    assert parsed["email"] == "danielle@sftoyota.com"
    assert parsed["full_name"] == "Janet Valla"


def test_parse_returns_none_without_email_or_name():
    person = {
        "personal_emails": ["eeefe37a523b32ff461ac14887639058"],
        "linkedinurl": "https://www.linkedin.com/in/someone",
    }
    assert parse_rb2b_business_profile(person) is None
