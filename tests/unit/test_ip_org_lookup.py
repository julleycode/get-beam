"""Unit gates over the IP→org lookup and its position in the resolver ladder.

No Postgres: the session is a stub whose ``execute`` is scripted, so the
flag-gating, fail-open and ladder-ordering contracts are provable without a
database. The real longest-prefix SQL semantics are covered by the integration
lane (only Postgres can prove ``>>=`` + ``masklen`` ordering).
"""

import pytest

from apps.api.services import company_resolver
from apps.api.services.ip_org_lookup import (
    _LOOKUP_SQL,
    _V2_ROUTE_ORIGIN_SQL,
    lookup_ip_org,
    lookup_ip_org_v2,
)

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


# ── v2 (fusion) ──────────────────────────────────────────────────────────────


class _MultiQueryResult:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def scalar(self):
        return self._rows[0][0] if self._rows else None


class _V2StubSession:
    """Answers v2's three/four queries by matching on the SQL text.

    v2 issues distinct statements, so keying the scripted answers off a
    substring of each is enough to exercise the orchestration without Postgres.
    The SQL semantics themselves (``>>=`` containment, ``masklen`` ordering, the
    ``org_kind`` filter) are the integration lane's job — a stub cannot prove
    them and pretending otherwise would be a vacuous green.
    """

    def __init__(self, route=None, holders=(), roas=(), corpus=False, raises=None):
        self.route = route
        self.holders = list(holders)
        self.roas = list(roas)
        self.corpus = corpus
        self._raises = raises
        self.executed: list = []
        self.rolled_back = False

    async def execute(self, stmt, params=None):
        sql = str(stmt).lower()
        self.executed.append(sql)
        if self._raises is not None:
            raise self._raises
        if "exists(" in sql:
            return _MultiQueryResult([(self.corpus,)])
        if "rpki_roas" in sql:
            return _MultiQueryResult(self.roas)
        if "registered_holder" in sql:
            return _MultiQueryResult(self.holders)
        return _MultiQueryResult([self.route] if self.route else [])

    async def rollback(self):
        self.rolled_back = True

    async def commit(self):
        return None


_ORG_ROUTE = ("acme widgets", "Acme Widgets, Inc.", 64500, "org", "10.1.2.0/24")


class TestLookupIpOrgV2:
    @pytest.fixture(autouse=True)
    def _flags(self, monkeypatch):
        monkeypatch.setattr(
            company_resolver.settings, "ip_org_lookup_enabled", True, raising=False
        )
        from apps.api.services import ip_org_fusion

        ip_org_fusion.invalidate_rir_corpus_cache()
        yield
        ip_org_fusion.invalidate_rir_corpus_cache()

    async def test_it_is_inert_when_the_lookup_flag_is_off(self, monkeypatch):
        monkeypatch.setattr(
            company_resolver.settings, "ip_org_lookup_enabled", False, raising=False
        )
        db = _V2StubSession(route=_ORG_ROUTE)
        assert await lookup_ip_org_v2(db, "10.1.2.3") is None
        assert db.executed == []

    async def test_a_hit_returns_a_scored_hypothesis(self):
        db = _V2StubSession(route=_ORG_ROUTE, holders=[("10.1.2.0/24", "xx", "arin:xx")], corpus=True)
        got = await lookup_ip_org_v2(db, "10.1.2.3")
        assert got is not None
        assert got["organization"] == "acme widgets"
        assert got["classification"] == "registered_operator"
        assert 0.05 <= got["confidence"] <= 0.65

    async def test_no_route_origin_row_yields_no_hypothesis(self):
        assert await lookup_ip_org_v2(_V2StubSession(route=None), "10.1.2.3") is None

    async def test_a_database_error_is_fail_open(self):
        db = _V2StubSession(raises=RuntimeError('relation "rpki_roas" does not exist'))
        assert await lookup_ip_org_v2(db, "10.1.2.3") is None
        assert db.rolled_back is True

    async def test_a_warm_corpus_cache_saves_the_fourth_query(self):
        """The query budget is 3 warm / 4 cold on the live resolver path."""
        cold = _V2StubSession(route=_ORG_ROUTE, corpus=True)
        await lookup_ip_org_v2(cold, "10.1.2.3")
        assert sum(1 for s in cold.executed if "exists(" in s) == 1

        warm = _V2StubSession(route=_ORG_ROUTE, corpus=True)
        await lookup_ip_org_v2(warm, "10.1.2.3")
        assert sum(1 for s in warm.executed if "exists(" in s) == 0
        assert len(warm.executed) == 3

    async def test_v1_is_untouched_by_v2(self):
        """v1 stays the flag-off path, byte-identical."""
        sql = str(_LOOKUP_SQL).lower()
        assert "relationship_type" not in sql


class TestOrgKindIsolation:
    """G11 / AC4.4a — the anti-``cdurham@fastly.com`` gate.

    Resolving a Comcast or Fastly prefix to "Comcast"/"Fastly" as a visitor's
    employer is fabrication. ``eyeball`` alone is ~27% of the loaded corpus, so
    this is the single largest such risk in the dataset.

    Filtering is strictly safer than penalizing: a confidence penalty still
    writes a row. These assertions exist so that relaxing the predicate fails
    loudly instead of silently widening what becomes a "company".
    """

    def test_org_kind_isolation_predicate_is_present_in_the_v2_query(self):
        sql = str(_V2_ROUTE_ORIGIN_SQL).lower()
        assert "org_kind = 'org'" in sql, "v2 must not widen beyond org_kind='org'"
        assert "relationship_type = 'route_origin'" in sql
        assert "prefix >>=" in sql
        assert "order by masklen(prefix) desc" in sql
        assert "limit 1" in sql

    @pytest.mark.parametrize("kind", ["datacenter", "cdn", "eyeball", "registry"])
    async def test_org_kind_isolation_yields_no_hypothesis_and_no_write(
        self, kind, monkeypatch
    ):
        """With fusion ON, a non-org prefix must produce nothing at any confidence.

        The stub reproduces the DB's behavior for the filtered predicate: the
        route-origin query returns no row for a non-org prefix. The predicate
        text itself is asserted above, and the per-kind SQL semantics are proven
        against Postgres in the integration lane.
        """
        monkeypatch.setattr(
            company_resolver.settings, "ip_org_lookup_enabled", True, raising=False
        )
        monkeypatch.setattr(
            company_resolver.settings, "ip_org_fusion_enabled", True, raising=False
        )
        monkeypatch.setattr(
            company_resolver.settings, "company_graph_enabled", True, raising=False
        )

        wrote = False

        async def _capture(*a, **kw):
            nonlocal wrote
            wrote = True

        monkeypatch.setattr(company_resolver, "_write_through_company_graph", _capture)

        # org_kind=kind → the filtered query matches nothing.
        db = _V2StubSession(route=None, corpus=True)
        assert await lookup_ip_org_v2(db, "10.1.2.3") is None

        out = await company_resolver._resolve_via_local_ip_org(db, "10.1.2.3")
        assert out is None
        assert wrote is False, f"a {kind} prefix must never reach company_graph"


class TestResolverFusionBranch:
    async def test_fusion_off_is_byte_identical_to_phase_2(self, monkeypatch):
        """AC4.5 — the flag-off path must not move at all."""
        monkeypatch.setattr(
            company_resolver.settings, "ip_org_lookup_enabled", True, raising=False
        )
        monkeypatch.setattr(
            company_resolver.settings, "ip_org_fusion_enabled", False, raising=False
        )
        monkeypatch.setattr(
            company_resolver.settings, "company_graph_enabled", True, raising=False
        )

        v2_called = False

        async def _v2(db, ip):
            nonlocal v2_called
            v2_called = True
            return None

        monkeypatch.setattr("apps.api.services.ip_org_lookup.lookup_ip_org_v2", _v2)

        async def _hit(db, ip):
            return {"org_name": "microsoft", "domain": None, "asn": 8075, "org_kind": "org"}

        monkeypatch.setattr("apps.api.services.ip_org_lookup.lookup_ip_org", _hit)

        captured: dict = {}

        async def _capture(db, ip, domain, company_name, source, confidence):
            captured.update(source=source, confidence=confidence, company_name=company_name)

        monkeypatch.setattr(company_resolver, "_write_through_company_graph", _capture)

        await company_resolver._resolve_via_local_ip_org(_StubSession(), "13.107.6.1")
        assert v2_called is False
        assert captured == {
            "source": "rir_asn",
            "confidence": 0.45,
            "company_name": "microsoft",
        }

    async def test_fusion_on_writes_exactly_one_row_with_the_fused_confidence(
        self, monkeypatch
    ):
        """AC4.6 — one fused row, same source string, no new source value."""
        monkeypatch.setattr(
            company_resolver.settings, "ip_org_lookup_enabled", True, raising=False
        )
        monkeypatch.setattr(
            company_resolver.settings, "ip_org_fusion_enabled", True, raising=False
        )
        monkeypatch.setattr(
            company_resolver.settings, "company_graph_enabled", True, raising=False
        )

        async def _v2(db, ip):
            return {
                "organization": "acme widgets",
                "organization_raw": "Acme Widgets, Inc.",
                "domain": None,
                "classification": "registered_operator",
                "confidence": 0.6,
                "relationship_types": ["route_origin", "registered_holder"],
                "evidence": ["e"],
                "uncertainty": [],
            }

        monkeypatch.setattr("apps.api.services.ip_org_lookup.lookup_ip_org_v2", _v2)

        writes: list = []

        async def _capture(db, ip, domain, company_name, source, confidence):
            writes.append((source, confidence, company_name))

        monkeypatch.setattr(company_resolver, "_write_through_company_graph", _capture)

        out = await company_resolver._resolve_via_local_ip_org(_StubSession(), "10.1.2.3")
        assert out is None  # domain mapping is out of this phase
        assert writes == [("rir_asn", 0.6, "acme widgets")]

    async def test_the_fused_confidence_can_never_outrank_the_paid_path(self):
        from apps.api.services.ip_org_fusion import CONFIDENCE_CEILING

        assert CONFIDENCE_CEILING < 0.7
