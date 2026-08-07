"""Unit gates over the IP→org lookup and its position in the resolver ladder.

No Postgres: the session is a stub whose ``execute`` is scripted, so the
flag-gating, fail-open and ladder-ordering contracts are provable without a
database. The real longest-prefix SQL semantics are covered by the integration
lane (only Postgres can prove ``>>=`` + ``masklen`` ordering).
"""

import pytest

from apps.api.services import company_resolver
from apps.api.services.ip_org_lookup import _LOOKUP_SQL, lookup_ip_org

pytestmark = pytest.mark.unit


class _StubResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _StubSession:
    """Records executed statements; returns a scripted row (or raises)."""

    def __init__(self, row=None, raises: Exception | None = None):
        self._row = row
        self._raises = raises
        self.executed: list = []
        self.rolled_back = False

    async def execute(self, stmt, params=None):
        self.executed.append((stmt, params))
        if self._raises is not None:
            raise self._raises
        return _StubResult(self._row)

    async def rollback(self):
        self.rolled_back = True

    async def commit(self):
        return None


class TestLookupIpOrg:
    async def test_it_is_inert_when_the_flag_is_off(self, monkeypatch):
        monkeypatch.setattr(
            company_resolver.settings, "ip_org_lookup_enabled", False, raising=False
        )
        db = _StubSession(row=("microsoft", None, 8075, "org"))
        assert await lookup_ip_org(db, "13.107.6.1") is None
        assert db.executed == [], "flag-off must not issue a query at all"

    async def test_it_returns_the_matched_row(self, monkeypatch):
        monkeypatch.setattr(
            company_resolver.settings, "ip_org_lookup_enabled", True, raising=False
        )
        db = _StubSession(row=("microsoft", None, 8075, "org"))
        match = await lookup_ip_org(db, "13.107.6.1")
        assert match == {
            "org_name": "microsoft",
            "domain": None,
            "asn": 8075,
            "org_kind": "org",
        }

    async def test_no_match_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            company_resolver.settings, "ip_org_lookup_enabled", True, raising=False
        )
        assert await lookup_ip_org(_StubSession(row=None), "1.2.3.4") is None

    async def test_an_empty_ip_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            company_resolver.settings, "ip_org_lookup_enabled", True, raising=False
        )
        assert await lookup_ip_org(_StubSession(row=None), "") is None

    async def test_a_database_error_is_fail_open(self, monkeypatch):
        monkeypatch.setattr(
            company_resolver.settings, "ip_org_lookup_enabled", True, raising=False
        )
        db = _StubSession(raises=RuntimeError('relation "ip_org_prefixes" does not exist'))
        assert await lookup_ip_org(db, "1.2.3.4") is None
        assert db.rolled_back is True

    def test_the_query_is_longest_prefix_and_org_only(self):
        sql = str(_LOOKUP_SQL).lower()
        # These three clauses ARE the contract — dropping the ORDER BY silently
        # attributes a customer /24 to whoever holds the covering /8.
        assert "prefix >>=" in sql
        assert "order by masklen(prefix) desc" in sql
        assert "org_kind = 'org'" in sql
        assert "limit 1" in sql


class TestResolverLadder:
    """`_resolve_via_local_ip_org` runs only after rDNS misses, and only on-flag."""

    async def test_it_is_inert_without_a_session(self, monkeypatch):
        monkeypatch.setattr(
            company_resolver.settings, "ip_org_lookup_enabled", True, raising=False
        )
        assert await company_resolver._resolve_via_local_ip_org(None, "1.2.3.4") is None

    async def test_it_is_inert_when_the_flag_is_off(self, monkeypatch):
        monkeypatch.setattr(
            company_resolver.settings, "ip_org_lookup_enabled", False, raising=False
        )
        called = False

        async def _boom(db, ip):
            nonlocal called
            called = True
            return {"org_name": "x", "domain": None, "asn": 1, "org_kind": "org"}

        monkeypatch.setattr(
            "apps.api.services.ip_org_lookup.lookup_ip_org", _boom
        )
        out = await company_resolver._resolve_via_local_ip_org(_StubSession(), "1.2.3.4")
        assert out is None
        assert called is False

    async def test_a_hit_writes_through_as_rir_asn_with_the_company_name(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            company_resolver.settings, "ip_org_lookup_enabled", True, raising=False
        )
        monkeypatch.setattr(
            company_resolver.settings, "company_graph_enabled", True, raising=False
        )

        async def _hit(db, ip):
            return {
                "org_name": "microsoft",
                "domain": None,
                "asn": 8075,
                "org_kind": "org",
            }

        monkeypatch.setattr("apps.api.services.ip_org_lookup.lookup_ip_org", _hit)

        captured: dict = {}

        async def _capture(db, ip, domain, company_name, source, confidence):
            captured.update(
                ip=ip,
                domain=domain,
                company_name=company_name,
                source=source,
                confidence=confidence,
            )

        monkeypatch.setattr(
            company_resolver, "_write_through_company_graph", _capture
        )

        out = await company_resolver._resolve_via_local_ip_org(
            _StubSession(), "13.107.6.1"
        )
        # Phase 1/2 store no domain, so the ladder still reports "no domain" —
        # the value of the hit is the persisted company_name.
        assert out is None
        assert captured["source"] == "rir_asn"
        assert captured["confidence"] == 0.45
        assert captured["company_name"] == "microsoft"
        # Below rDNS (0.5) and paid (0.7) so better sources shadow it on read.
        assert captured["confidence"] < 0.5

    async def test_a_miss_writes_nothing(self, monkeypatch):
        monkeypatch.setattr(
            company_resolver.settings, "ip_org_lookup_enabled", True, raising=False
        )
        monkeypatch.setattr(
            company_resolver.settings, "company_graph_enabled", True, raising=False
        )

        async def _miss(db, ip):
            return None

        monkeypatch.setattr("apps.api.services.ip_org_lookup.lookup_ip_org", _miss)

        wrote = False

        async def _capture(*a, **kw):
            nonlocal wrote
            wrote = True

        monkeypatch.setattr(company_resolver, "_write_through_company_graph", _capture)
        assert (
            await company_resolver._resolve_via_local_ip_org(_StubSession(), "1.2.3.4")
            is None
        )
        assert wrote is False
