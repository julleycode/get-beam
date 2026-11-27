"""G1 — click-id extraction from event URLs (conversion-apis AC-1)."""

import re

import pytest

from apps.api.services.click_ids import (
    CLICK_ID_URL_REGEX,
    build_visitor_click_ids,
    extract_click_ids,
    google_ad_identifier,
    meta_fbc,
)

pytestmark = pytest.mark.unit


def test_should_parse_fbclid_gclid_wbraid_gbraid_li_fat_id_from_event_url():
    url = "https://x.com/p?fbclid=FB1&gclid=G1&wbraid=W1&gbraid=GB1&li_fat_id=L1&utm_source=a"
    assert extract_click_ids(url) == {
        "fbclid": "FB1", "gclid": "G1", "wbraid": "W1", "gbraid": "GB1", "li_fat_id": "L1",
    }


@pytest.mark.parametrize(
    "url",
    [None, "", "https://x.com/", "https://x.com/?utm_source=g", "https://x.com/?gclid=", "not a url"],
)
def test_no_click_id_yields_empty(url):
    assert extract_click_ids(url) == {}


def test_first_value_wins_and_fragment_ignored():
    assert extract_click_ids("https://x.com/?gclid=A&gclid=B#gclid=C") == {"gclid": "A"}


def test_value_is_length_capped():
    assert len(extract_click_ids("https://x.com/?gclid=" + "a" * 900)["gclid"]) == 500


def test_build_visitor_click_ids_none_when_empty_never_empty_dict():
    assert build_visitor_click_ids("https://x.com/", 123) is None


def test_fbc_ts_only_with_fbclid():
    assert build_visitor_click_ids("https://x.com/?gclid=G", 5) == {"gclid": "G"}
    assert build_visitor_click_ids("https://x.com/?fbclid=F", 1700000000123) == {
        "fbclid": "F", "fbc_ts": 1700000000123,
    }


def test_meta_fbc_format():
    assert meta_fbc({"fbclid": "F", "fbc_ts": 42}) == "fb.1.42.F"
    assert meta_fbc({"gclid": "G"}) is None
    assert meta_fbc(None) is None


def test_google_identifier_priority_gclid_wbraid_gbraid():
    assert google_ad_identifier({"gbraid": "3", "wbraid": "2", "gclid": "1"}) == ("gclid", "1")
    assert google_ad_identifier({"gbraid": "3", "wbraid": "2"}) == ("wbraid", "2")
    assert google_ad_identifier({"gbraid": "3"}) == ("gbraid", "3")
    assert google_ad_identifier({"fbclid": "F"}) is None


@pytest.mark.parametrize(
    "url,match",
    [
        ("https://x.com/?gclid=A", True),
        ("https://x.com/?a=1&li_fat_id=Z", True),
        ("https://x.com/?gclid=", False),
        ("https://x.com/?mygclid=A", False),
        ("https://x.com/", False),
    ],
)
def test_sql_prefilter_regex_agrees_with_parser(url, match):
    assert bool(re.search(CLICK_ID_URL_REGEX, url)) is match
    assert bool(extract_click_ids(url)) is match
