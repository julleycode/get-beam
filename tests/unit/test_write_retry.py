"""Phase 12: platform write ops (post_comment) must only retry when no write
could have happened — otherwise a retry double-posts."""

import httpx

from apps.api.services.platforms.base import _is_write_retryable


def _http_error(status: int) -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError(
        "x", request=httpx.Request("POST", "https://x.test"), response=httpx.Response(status)
    )


def test_connection_failures_are_retried():
    # The request provably never reached the server → safe to retry.
    assert _is_write_retryable(httpx.ConnectError("x")) is True
    assert _is_write_retryable(httpx.ConnectTimeout("x")) is True


def test_429_is_retried():
    # Rate-limited → no write occurred.
    assert _is_write_retryable(_http_error(429)) is True


def test_5xx_and_read_timeout_are_not_retried():
    # The write MAY have succeeded — retrying would double-post.
    assert _is_write_retryable(_http_error(500)) is False
    assert _is_write_retryable(_http_error(502)) is False
    assert _is_write_retryable(_http_error(503)) is False
    assert _is_write_retryable(httpx.ReadTimeout("x")) is False


def test_other_exceptions_not_retried():
    assert _is_write_retryable(ValueError("x")) is False
