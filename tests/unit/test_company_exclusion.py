"""Company exclusion list — pure matcher, validation, CSV parse, log hygiene (G1, G5)."""

import logging

import pytest
import structlog

import apps.api.main  # noqa: F401
from apps.api.config import settings
from apps.api.services import company_exclusion as ce
from apps.api.services.enricher import _FREE_MAIL_DOMAINS

pytestmark = pytest.mark.unit


def test_flag_defaults_off():
    assert settings.company_exclusion_enabled is False


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Acme.com", "acme.com"),
        ("https://www.acme.com/pricing?x=1", "acme.com"),
        ("http://user:pw@eu.Acme.com:8080/a", "eu.acme.com"),
        ("jane@Acme.COM", "acme.com"),
        ("acme.com.", "acme.com"),
        ("  www.acme.co.uk  ", "acme.co.uk"),
        ("", None),
        (None, None),
        ("not a domain", None),
    ],
)
def test_should_normalize_domain(raw, expected):
    assert ce.normalize_domain(raw) == expected


def test_should_normalize_and_match_parent_domain():
    ex = {"acme.com": "customer"}
    assert ce.match_excluded(["a.b.eu.acme.com"], ex) == "customer"
    assert ce.match_excluded(["jane@eu.acme.com"], ex) == "customer"
    assert ce.match_excluded(["acme.com"], ex) == "customer"
    assert ce.match_excluded(["notacme.com"], ex) is None
    assert ce.match_excluded(["acme.com.evil.io"], ex) is None
    assert ce.match_excluded([None, ""], ex) is None
    assert ce.match_excluded(["acme.com"], {}) is None


def test_parent_walk_stops_at_two_labels():
    assert list(ce._parent_walk("a.b.acme.com")) == ["a.b.acme.com", "b.acme.com", "acme.com"]
    # a bare "com" entry could never be matched even if it slipped in
    assert ce.match_excluded(["acme.com"], {"com": "other"}) is None


@pytest.mark.parametrize(
    "raw,err",
    [
        ("gmail.com", "freemail_domain"),
        ("https://www.outlook.com", "freemail_domain"),
        ("com", "invalid_domain"),
        ("co.uk", "public_suffix"),
        ("com.au", "public_suffix"),
        ("io", "invalid_domain"),
        ("", "invalid_domain"),
    ],
)
def test_should_reject_freemail_and_public_suffix(raw, err):
    assert ce.validate_exclusion_domain(raw) == (None, err)


def test_valid_domain_accepted():
    assert ce.validate_exclusion_domain("https://www.Acme.co.uk/x") == ("acme.co.uk", None)


def test_freemail_set_is_superset_of_enricher():
    assert _FREE_MAIL_DOMAINS <= ce.FREEMAIL_DOMAINS


def test_csv_parse_rows_errors_and_dedupe():
    data = (
        "domain,company_name,reason\n"
        "acme.com,Acme,customer\n"
        "gmail.com,,competitor\n"
        "rival.io,Rival,competitor\n"
        "bad.org,,enemy\n"
        "\n"
        "acme.com,Acme Inc,other\n"
    ).encode()
    valid, errors = ce.parse_exclusions_csv(data)
    by = {r["domain"]: r for r in valid}
    assert set(by) == {"acme.com", "rival.io"}
    assert by["acme.com"]["reason"] == "other"  # last row wins
    assert by["acme.com"]["company_name"] == "Acme Inc"
    assert {e["error"] for e in errors} == {"freemail_domain", "invalid_reason"}
    assert [e["row"] for e in errors] == [3, 5]


def test_csv_parse_defaults_reason_and_no_header():
    valid, errors = ce.parse_exclusions_csv(b"acme.com\n")
    assert valid == [{"domain": "acme.com", "company_name": None, "reason": "other", "note": None}]
    assert errors == []


def test_csv_row_cap():
    rows = "".join(f"c{i}.com,,other\n" for i in range(ce.MAX_IMPORT_ROWS + 5))
    valid, errors = ce.parse_exclusions_csv(rows.encode())
    assert len(valid) == ce.MAX_IMPORT_ROWS
    assert errors and errors[-1]["error"] == "too_many_rows"


def test_csv_size_cap_constant():
    assert ce.MAX_IMPORT_BYTES == 1_048_576


def test_should_log_counts_only(caplog):
    captured: list[dict] = []

    def _capture(_logger, _name, event_dict):
        captured.append(dict(event_dict))
        raise structlog.DropEvent

    old = structlog.get_config()
    structlog.configure(processors=[_capture])
    try:
        ce.log_applied("site_1", "campaign_send", 3)
    finally:
        structlog.configure(**old)
    assert captured, "no log event captured"
    ev = captured[0]
    assert ev["event"] == "company_exclusion_applied"
    assert set(ev) <= {"event", "site_id", "surface", "excluded_count", "level", "timestamp"}
    flat = " ".join(str(v) for v in ev.values())
    assert "@" not in flat and ".com" not in flat
