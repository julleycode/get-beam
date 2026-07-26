"""Unit tests for the Redis read timeout hardening (AC12, Phase 4d).

A Redis that accepts the TCP connection and then never answers must raise a
bounded timeout instead of blocking an awaited call forever.

Per validate-contract E10/C7: these tests MUST NOT call ``get_redis()`` — the
unit-lane conftest pins ``REDIS_URL=redis://localhost:6379/15`` and a stray
local Redis container is a known cross-run poisoning source. The stalled-server
case binds its own listening socket.
"""

import ast
import asyncio
import inspect
import socket
import time

import pytest
import redis.exceptions
from redis.asyncio import Redis

from apps.api.services import redis_client

pytestmark = pytest.mark.unit


def _from_url_kwargs() -> dict:
    """Extract the literal keyword args of the Redis.from_url call in get_redis."""
    tree = ast.parse(inspect.getsource(redis_client.get_redis))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name == "from_url":
                return {
                    kw.arg: (kw.value.value if isinstance(kw.value, ast.Constant) else kw.value)
                    for kw in node.keywords
                }
    raise AssertionError("no Redis.from_url call found in get_redis")


def test_get_redis_sets_socket_timeout():
    """get_redis must pass an explicit socket_timeout (read timeout)."""
    assert _from_url_kwargs().get("socket_timeout") == 5


def test_get_redis_disables_retry_on_timeout():
    """A timed-out call must surface, not be silently retried."""
    assert _from_url_kwargs().get("retry_on_timeout") is False


def test_get_redis_keeps_socket_connect_timeout():
    """Connect timeout must not regress while adding the read timeout."""
    assert _from_url_kwargs().get("socket_connect_timeout") == 5


@pytest.mark.asyncio
async def test_stalled_redis_raises_bounded_timeout():
    """A server that accepts and never responds raises TimeoutError, bounded."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    client = Redis.from_url(
        f"redis://127.0.0.1:{port}/0",
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=0.5,
        retry_on_timeout=False,
    )
    try:
        started = time.monotonic()
        with pytest.raises((redis.exceptions.TimeoutError, asyncio.TimeoutError)):
            await client.ping()
        assert time.monotonic() - started < 5
    finally:
        await client.aclose()
        listener.close()
