"""Integration-lane fixtures.

The production module-level engine (`apps.api.models.database.engine`) is a
process-wide singleton, but pytest-asyncio gives every test its OWN event loop
(`asyncio_default_fixture_loop_scope = "function"`). Background jobs such as
`outcome_digest.send_weekly_outcome_digests` and
`referral_activation.activate_pending_referrals` open sessions through the
global `async_session`, so the first such test parks an asyncpg connection in
the shared pool bound to ITS loop, and the next test that checks it out fails
with "Future attached to a different loop". Which test fails depends purely on
run order.

Dropping the pool (without closing — the old loop is gone, so closing would
itself raise) before each test makes every test start with a fresh pool bound
to its own loop.
"""

import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def _fresh_global_engine_pool():
    from apps.api.models.database import engine

    await engine.dispose(close=False)
    yield
