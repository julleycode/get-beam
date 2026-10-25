"""TinyFish client: mock mode, errors[] inside a 200, transient retry, cost ledger."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from apps.api.services import tinyfish_client as tf

pytestmark = pytest.mark.unit


def _resp(status: int, body: dict) -> MagicMock:
    req = httpx.Request("GET", "https://api.tinyfish.ai/v1/x")
    r = httpx.Response(status, json=body, request=req)
    return r


class _Client:
    """Minimal async-context httpx.AsyncClient stand-in returning queued responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def _next(self, method, url, **k):
        self.calls += 1
        self.requests.append((method, url, k))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def get(self, url, **k):
        return await self._next("GET", url, **k)

    async def post(self, url, **k):
        return await self._next("POST", url, **k)


@pytest.fixture(autouse=True)
def _live_settings(monkeypatch):
    monkeypatch.setattr(tf.settings, "mock_external_apis", False)
    monkeypatch.setattr(tf.settings, "tinyfish_api_key", "k")
    # no real backoff sleeping
    monkeypatch.setattr(tf._http_search.retry, "sleep", AsyncMock(), raising=False)
    monkeypatch.setattr(tf._http_fetch.retry, "sleep", AsyncMock(), raising=False)


async def test_mock_mode_is_deterministic_and_offline(monkeypatch):
    monkeypatch.setattr(tf.settings, "mock_external_apis", True)
    with patch("httpx.AsyncClient", side_effect=AssertionError("network")), \
         patch.object(tf, "log_api_call", AsyncMock()) as log:
        a = await tf.search("Ava Chen Example")
        b = await tf.search("Ava Chen Example")
        res, errs = await tf.fetch([a[0]["url"]])
    assert a == b and len(a) == 2
    assert res and errs == []
    log.assert_not_called()


async def test_fetch_errors_inside_200_are_returned_not_raised():
    body = {
        "results": [{"url": "https://a.example.com", "text": "hello"}],
        "errors": [{"url": "https://www.linkedin.com/in/x", "error": "blocked"}],
    }
    client = _Client([_resp(200, body)])
    with patch("httpx.AsyncClient", return_value=client), \
         patch.object(tf, "log_api_call", AsyncMock()) as log:
        res, errs = await tf.fetch(["https://a.example.com", "https://www.linkedin.com/in/x"])
    assert res == [{"url": "https://a.example.com", "final_url": "https://a.example.com", "text": "hello"}]
    assert errs[0]["error"] == "blocked"
    kw = log.await_args.kwargs
    assert kw["provider"] == "tinyfish_fetch" and kw["success"] is True


async def test_search_retries_transient_then_succeeds():
    client = _Client([
        _resp(503, {}),
        httpx.ConnectError("boom"),
        _resp(200, {"results": [{"url": "https://x.example.com", "title": "t", "snippet": "s"}]}),
    ])
    with patch("httpx.AsyncClient", return_value=client), \
         patch.object(tf, "log_api_call", AsyncMock()) as log:
        out = await tf.search("q")
    assert client.calls == 3
    assert out[0]["url"] == "https://x.example.com"
    assert log.await_args.kwargs["provider"] == "tinyfish_search"


async def test_search_non_transient_raises_and_logs_failure():
    client = _Client([_resp(401, {})])
    with patch("httpx.AsyncClient", return_value=client), \
         patch.object(tf, "log_api_call", AsyncMock()) as log:
        with pytest.raises(httpx.HTTPStatusError):
            await tf.search("q")
    assert client.calls == 1
    assert log.await_args.kwargs["success"] is False


async def test_log_never_contains_query_or_urls():
    client = _Client([_resp(200, {"results": []})])
    with patch("httpx.AsyncClient", return_value=client), \
         patch.object(tf, "log_api_call", AsyncMock()) as log:
        await tf.search("Secret Person Corp")
    assert "Secret" not in repr(log.await_args)


def test_parse_search_drops_non_http_urls():
    out = tf._parse_search({"results": [{"url": "javascript:x"}, {"link": "https://ok.example"}, "junk"]})
    assert [r["url"] for r in out] == ["https://ok.example"]


# Response shapes copied from docs.tinyfish.ai (verified 25-10-26).
DOC_SEARCH = {
    "query": "Ava Chen Example Labs",
    "results": [{"position": 1, "site_name": "LinkedIn", "title": "Ava Chen - Example Labs",
                 "snippet": "Head of Growth", "url": "https://www.linkedin.com/in/ava"}],
    "total_results": 1, "page": 1,
}
DOC_FETCH = {
    "results": [{"url": "https://examplelabs.com/team", "final_url": "https://examplelabs.com/team/",
                 "title": "Team", "description": "d", "language": "en", "format": "markdown",
                 "text": "# Team"}],
    "errors": [{"url": "https://www.linkedin.com/in/ava", "error": "blocked"}],
}


async def test_search_exact_request_and_doc_shape():
    client = _Client([_resp(200, DOC_SEARCH)])
    with patch("httpx.AsyncClient", return_value=client), patch.object(tf, "log_api_call", AsyncMock()):
        out = await tf.search("Ava Chen Example Labs")
    method, url, kw = client.requests[0]
    assert (method, url) == ("GET", "https://api.search.tinyfish.ai")
    assert kw["headers"]["X-API-Key"] == "k"
    assert kw["params"] == {"query": "Ava Chen Example Labs", "domain_type": "web"}
    assert out == [{"url": "https://www.linkedin.com/in/ava", "title": "Ava Chen - Example Labs",
                    "site_name": "LinkedIn", "snippet": "Head of Growth"}]


async def test_fetch_exact_request_and_doc_shape():
    client = _Client([_resp(200, DOC_FETCH)])
    urls = ["https://examplelabs.com/team", "https://www.linkedin.com/in/ava"]
    with patch("httpx.AsyncClient", return_value=client), patch.object(tf, "log_api_call", AsyncMock()):
        res, errs = await tf.fetch(urls)
    method, url, kw = client.requests[0]
    assert (method, url) == ("POST", "https://api.fetch.tinyfish.ai")
    assert kw["headers"]["X-API-Key"] == "k"
    assert kw["headers"]["Content-Type"] == "application/json"
    assert kw["json"] == {"urls": urls, "format": "markdown"}
    assert res == [{"url": "https://examplelabs.com/team", "final_url": "https://examplelabs.com/team/",
                    "text": "# Team"}]
    assert errs == [{"url": "https://www.linkedin.com/in/ava", "error": "blocked"}]
