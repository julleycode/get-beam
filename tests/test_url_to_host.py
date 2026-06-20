"""_url_to_host scopes Leadpipe's account-wide /v1/data feed to one site via
the `domain` param (the API has no per-IP/per-pixel filter). Bad host parsing
would silently scope to the wrong domain (zero matches), so pin the behavior.
"""

import pytest

from apps.api.services.identity_resolver import _url_to_host


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://grade.coach", "grade.coach"),
        ("http://www.grade.coach/pricing?x=1", "grade.coach"),  # scheme + www + path stripped
        ("grade.coach", "grade.coach"),                          # bare host, no scheme
        ("https://sub.example.co.uk/", "sub.example.co.uk"),     # subdomain kept
        ("https://WWW.Example.com", "example.com"),              # urlparse lowercases host
        (None, None),
        ("", None),
    ],
)
def test_url_to_host(url, expected):
    assert _url_to_host(url) == expected
