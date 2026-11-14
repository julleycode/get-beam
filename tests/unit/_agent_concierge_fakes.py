"""Shared fakes for the WS3 agent-concierge unit tests (no live DB / Redis)."""

from unittest.mock import AsyncMock, MagicMock


class FakeRedis:
    """Minimal async Redis: SET NX EX, INCR, EXPIRE, DELETE."""

    def __init__(self):
        self.store: dict = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def incr(self, key):
        self.store[key] = int(self.store.get(key, 0)) + 1
        return self.store[key]

    async def expire(self, key, seconds):
        return True

    async def delete(self, key):
        return 1 if self.store.pop(key, None) is not None else 0


def mock_db():
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()
    owner_row = MagicMock()
    owner_row.first.return_value = ("owner@example.com",)
    db.execute = AsyncMock(return_value=owner_row)
    return db


class FakeSession:
    """Stands in for ``async_session()`` inside ``process_new_lead``."""

    def __init__(self, lead, site, owner="owner@example.com"):
        self.lead = lead
        self.site = site
        self.owner = owner
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, model, ident):
        return self.lead

    async def execute(self, stmt):
        r = MagicMock()
        r.scalar_one_or_none.return_value = self.site
        r.first.return_value = (self.owner,) if self.owner else None
        return r

    async def commit(self):
        self.commits += 1


def make_lead(n: int = 1, **over):
    from types import SimpleNamespace

    base = dict(
        id=f"00000000-0000-0000-0000-{n:012d}",
        site_id="site-1",
        tool_name="request_quote",
        use_case="a",
        company_size="b",
        evaluating_against="c",
        resolved_company_domain=None,
        notified=False,
    )
    base.update(over)
    return SimpleNamespace(**base)
