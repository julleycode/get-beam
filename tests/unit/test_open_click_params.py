"""Unit tests for campaign open/click plumbing:
- _tp_from_url extraction (events ingest → clicked_at attribution)
- decorate_links carrying _tp next to _bid
"""

import os
import uuid

from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from apps.api.routers.events import _tp_from_url  # noqa: E402
from apps.api.services.link_decorator import decorate_links  # noqa: E402


class TestTpFromUrl:
    def test_extracts_valid_uuid(self):
        tp = uuid.uuid4()
        assert _tp_from_url(f"https://x.com/page?_bid=abc&_tp={tp}") == tp

    def test_none_when_absent(self):
        assert _tp_from_url("https://x.com/page?_bid=abc") is None
        assert _tp_from_url(None) is None
        assert _tp_from_url("") is None

    def test_none_when_not_a_uuid(self):
        assert _tp_from_url("https://x.com/?_tp=hello") is None
        assert _tp_from_url("https://x.com/?_tp=") is None

    def test_survives_garbage_url(self):
        assert _tp_from_url("not a url at all _tp=nope") is None


class TestDecorateLinksTouchpoint:
    def test_appends_tp_after_bid(self):
        tp = str(uuid.uuid4())
        html = 'Visit <a href="https://acme.com/pricing">pricing</a>'
        out = decorate_links(html, "user@example.com", "acme.com", touchpoint_id=tp)
        assert "_bid=" in out
        assert f"_tp={tp}" in out

    def test_no_tp_without_touchpoint_id(self):
        html = 'Visit <a href="https://acme.com/pricing">pricing</a>'
        out = decorate_links(html, "user@example.com", "acme.com")
        assert "_bid=" in out
        assert "_tp=" not in out

    def test_foreign_host_untouched(self):
        tp = str(uuid.uuid4())
        html = 'See <a href="https://elsewhere.com/x">this</a>'
        out = decorate_links(html, "user@example.com", "acme.com", touchpoint_id=tp)
        assert "_tp=" not in out and "_bid=" not in out
