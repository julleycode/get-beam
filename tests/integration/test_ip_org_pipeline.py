"""Integration gates for the IP→org pipeline. Requires PostgreSQL.

Three things only Postgres can prove, and each of them is a silent-wrong-answer
bug if it regresses:

1. **Longest-prefix wins.** ``prefix >>= :ip`` matches a /8 AND a /24; without
   the ``masklen`` ordering the query returns whichever row the planner felt
   like, attributing a customer's /24 to the holder of the covering /8.
2. **The GiST index is usable.** The default GiST opclass for ``cidr`` does not
   support ``>>=``, so a missing ``inet_ops`` yields a valid-looking index that
   is never used.
3. **The staging swap is atomic and repeatable.** A swap that leaves
   staging-derived index names behind works once and then breaks the NEXT run on
   a name collision.
"""

from datetime import date

import pytest
from sqlalchemy import text

from apps.api.services import company_resolver
from apps.api.services.ip_org_lookup import lookup_ip_org

pytestmark = pytest.mark.integration


def _row(
    prefix: str,
    asn: int | None,
    org: str,
    kind: str = "org",
    relationship_type: str = "route_origin",
) -> dict:
    return {
        "prefix": prefix,
        "asn": asn,
        "org_name": org,
        "org_name_raw": org,
        "org_kind": kind,
        "relationship_type": relationship_type,
        "valid_from": None,
        "valid_to": None,
    }


def _rir_row(prefix: str, org: str) -> dict:
    """An RIR ``registered_holder`` row: ``org_kind='registry'`` and NO ASN.

    ``asn=None`` is the point, not an omission (D13). Delegated-extended records
    publish a range and an opaque handle and carry no autonomous-system number,
    so anything other than NULL here would be a value the source never stated.
    """
    return _row(prefix, None, org, "registry", "registered_holder")


async def _seed(db, rows: list[dict], source: str = "test") -> None:
    for r in rows:
        await db.execute(
            text(
                "INSERT INTO ip_org_prefixes "
                "(id, prefix, asn, org_name, org_name_raw, org_kind, source, "
                "relationship_type, valid_from, valid_to) "
                "VALUES (gen_random_uuid(), CAST(:prefix AS cidr), :asn, "
                ":org_name, :org_name_raw, :org_kind, :source, "
                ":relationship_type, :valid_from, :valid_to)"
            ),
            {**r, "source": source},
        )
    await db.commit()


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(
        company_resolver.settings, "ip_org_lookup_enabled", True, raising=False
    )


class TestLongestPrefixMatch:
    async def test_a_slash_24_beats_the_covering_slash_8(self, test_db):
        await _seed(
            test_db,
            [
                _row("10.0.0.0/8", 111, "wide isp", "org"),
                _row("10.1.2.0/24", 222, "narrow corp", "org"),
            ],
        )
        match = await lookup_ip_org(test_db, "10.1.2.55")
        assert match is not None
        assert match["org_name"] == "narrow corp"
        assert match["asn"] == 222

    async def test_an_address_outside_the_narrow_prefix_falls_back_to_the_wide_one(
        self, test_db
    ):
        await _seed(
            test_db,
            [
                _row("10.0.0.0/8", 111, "wide isp", "org"),
                _row("10.1.2.0/24", 222, "narrow corp", "org"),
            ],
        )
        match = await lookup_ip_org(test_db, "10.9.9.9")
        assert match is not None and match["org_name"] == "wide isp"

    async def test_a_non_org_kind_is_never_returned(self, test_db):
        await _seed(test_db, [_row("192.0.2.0/24", 13335, "cloudflare", "cdn")])
        assert await lookup_ip_org(test_db, "192.0.2.7") is None

    async def test_an_unmatched_address_returns_none(self, test_db):
        await _seed(test_db, [_row("203.0.113.0/24", 1, "someone", "org")])
        assert await lookup_ip_org(test_db, "198.51.100.4") is None


class TestGistIndex:
    async def test_the_containment_index_exists_with_inet_ops(self, test_db):
        row = (
            await test_db.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE tablename='ip_org_prefixes' "
                    "AND indexname='idx_ip_org_prefixes_prefix_gist'"
                )
            )
        ).first()
        assert row is not None, "GiST containment index missing"
        assert "gist" in row[0].lower()
        assert "inet_ops" in row[0].lower()


class TestStagingSwap:
    async def test_the_swap_replaces_the_dataset_wholesale(self, test_db):
        """Wholesale replacement is scoped to the swapping source (D1).

        The seed source matters now: since the carry-over landed, a swap replaces
        only its OWN source's rows and preserves everyone else's. Seeding as
        ``caida_pfx2as`` keeps this test asserting what it always meant —
        same-source replacement, not append. The cross-source half is
        ``test_a_swap_carries_over_the_other_sources_rows``.
        """
        from apps.api.services.ip_org_ingest import _load_staging_and_swap

        await _seed(
            test_db, [_row("10.0.0.0/8", 111, "old org", "org")], "caida_pfx2as"
        )
        await _load_staging_and_swap(
            test_db,
            [_row("172.16.0.0/12", 999, "new org", "org")],
            "caida_pfx2as",
            date(2026, 8, 1),
        )
        names = [
            r[0]
            for r in (
                await test_db.execute(text("SELECT org_name FROM ip_org_prefixes"))
            ).fetchall()
        ]
        assert names == ["new org"], "swap must replace, not append"

    async def test_index_names_are_restored_so_a_second_swap_works(self, test_db):
        from apps.api.services.ip_org_ingest import _load_staging_and_swap

        for org in ("first", "second"):
            await _load_staging_and_swap(
                test_db, [_row("172.16.0.0/12", 999, org, "org")], "caida_pfx2as", None
            )
        idx = {
            r[0]
            for r in (
                await test_db.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE tablename='ip_org_prefixes'"
                    )
                )
            ).fetchall()
        }
        assert "idx_ip_org_prefixes_prefix_gist" in idx
        assert "idx_ip_org_prefixes_asn" in idx
        assert "idx_ip_org_prefixes_org_name" in idx
        # The 4th canonical index, added with the evidence columns. Without a
        # matching ``_INDEX_TARGETS`` entry it falls through to the pkey fallback
        # and BOTH it and the real primary key get renamed to the same name,
        # aborting this second swap on ``relation already exists``.
        assert "idx_ip_org_prefixes_relationship_type" in idx
        assert not any(n.startswith("ip_org_prefixes_staging") for n in idx)
        pkeys = [n for n in idx if n == "ip_org_prefixes_pkey"]
        assert len(pkeys) == 1, f"expected exactly one pkey index, saw {sorted(idx)}"

    async def test_a_swap_carries_over_the_other_sources_rows(self, test_db):
        """AC1.3 — a CAIDA refresh must not delete the RIR corpus.

        The swap replaces the WHOLE table, so without the carry-over copy each
        source's refresh silently destroys the other two. This is the single
        highest-risk change in the phase: it sits in the only code path that can
        drop ~1M loaded rows.
        """
        from apps.api.services.ip_org_ingest import _load_staging_and_swap

        await _seed(test_db, [_rir_row("8.8.0.0/16", "xx-1-arin")], "rir_delegated")
        await _seed(test_db, [_row("10.0.0.0/8", 111, "old caida")], "caida_pfx2as")

        await _load_staging_and_swap(
            test_db,
            [_row("172.16.0.0/12", 999, "new caida")],
            "caida_pfx2as",
            date(2026, 8, 1),
        )

        by_source = {
            r[0]: r[1]
            for r in (
                await test_db.execute(
                    text("SELECT source, count(*) FROM ip_org_prefixes GROUP BY source")
                )
            ).fetchall()
        }
        assert by_source.get("rir_delegated") == 1, "RIR rows were destroyed by a CAIDA swap"
        assert by_source.get("caida_pfx2as") == 1, "CAIDA rows must be replaced, not appended"

        # And the carried-over row keeps its NULL asn — the copy is a straight
        # server-side SELECT, so a coercion here would be a schema mismatch.
        asn = (
            await test_db.execute(
                text("SELECT asn FROM ip_org_prefixes WHERE source = 'rir_delegated'")
            )
        ).scalar()
        assert asn is None


class TestLockSerialization:
    """G12 / AC1.5 — CAIDA and RIR refreshes serialize on ONE shared key.

    Both refreshes end in DROP + RENAME and both rely on copying the other
    source's rows into staging first. If they can interleave, the second RENAME
    discards rows the first just loaded. The schedules genuinely collide (weekly
    ∩ daily), so this is reachable, not theoretical.
    """

    async def test_a_second_refresh_backs_off_while_the_shared_lock_is_held(
        self, test_db, monkeypatch
    ):
        from apps.api.models.database import async_session
        from apps.api.models.ip_org_prefix import IP_ORG_WRITE_LOCK_KEY
        from apps.api.services import ip_org_rir_ingest

        await _seed(test_db, [_row("10.0.0.0/8", 111, "caida org")], "caida_pfx2as")
        await _seed(test_db, [_rir_row("8.8.0.0/16", "xx-1-arin")], "rir_delegated")

        async def _fake_fetch(_client, _url):
            return b"arin|US|ipv4|203.0.113.0|256|20200101|allocated|YY-2-ARIN\n"

        monkeypatch.setattr(ip_org_rir_ingest, "_get", _fake_fetch)

        # Hold the shared key in a separate session, exactly as the other job would.
        async with async_session() as holder:
            got = (
                await holder.execute(
                    text("SELECT pg_try_advisory_lock(hashtext(:k))"),
                    {"k": IP_ORG_WRITE_LOCK_KEY},
                )
            ).scalar()
            assert got is True
            try:
                status = await ip_org_rir_ingest.refresh_rir_allocations(dry_run=False)
            finally:
                await holder.execute(
                    text("SELECT pg_advisory_unlock(hashtext(:k))"),
                    {"k": IP_ORG_WRITE_LOCK_KEY},
                )

        assert status["status"] == "locked"

        by_source = {
            r[0]: r[1]
            for r in (
                await test_db.execute(
                    text("SELECT source, count(*) FROM ip_org_prefixes GROUP BY source")
                )
            ).fetchall()
        }
        assert by_source == {"caida_pfx2as": 1, "rir_delegated": 1}, (
            "a locked-out refresh must write nothing and destroy nothing"
        )


class TestLookupV2:
    """v2 against real ``>>=`` semantics — the half a stub cannot prove."""

    @pytest.fixture(autouse=True)
    def _clear_corpus_cache(self):
        from apps.api.services.ip_org_fusion import invalidate_rir_corpus_cache

        invalidate_rir_corpus_cache()
        yield
        invalidate_rir_corpus_cache()

    @pytest.mark.parametrize("kind", ["datacenter", "cdn", "eyeball", "registry"])
    async def test_org_kind_isolation_returns_none_for_every_non_org_kind(
        self, test_db, kind
    ):
        """AC4.4a against the real predicate, not a stub of it.

        ``eyeball`` is ~27% of the loaded corpus. Returning "Comcast" as a
        visitor's employer is the fabrication class this filter exists to close.
        """
        from apps.api.services.ip_org_lookup import lookup_ip_org_v2

        await _seed(test_db, [_row("192.0.2.0/24", 13335, "someone", kind)])
        assert await lookup_ip_org_v2(test_db, "192.0.2.7") is None

    async def test_org_kind_isolation_writes_no_company_graph_row(
        self, test_db, monkeypatch
    ):
        monkeypatch.setattr(
            company_resolver.settings, "ip_org_fusion_enabled", True, raising=False
        )
        monkeypatch.setattr(
            company_resolver.settings, "company_graph_enabled", True, raising=False
        )
        await _seed(test_db, [_row("192.0.2.0/24", 13335, "cloudflare", "cdn")])

        assert (
            await company_resolver._resolve_via_local_ip_org(test_db, "192.0.2.7")
            is None
        )
        count = (
            await test_db.execute(text("SELECT count(*) FROM company_graph"))
        ).scalar()
        assert count == 0, "a cdn prefix must never become a company at any confidence"

    async def test_an_exact_allocation_match_classifies_as_registered_operator(
        self, test_db
    ):
        """End-to-end: both evidence rows, real containment, real fusion."""
        from apps.api.services.ip_org_lookup import lookup_ip_org_v2

        await _seed(test_db, [_row("10.1.2.0/24", 64500, "acme widgets")], "caida_pfx2as")
        await _seed(test_db, [_rir_row("10.1.2.0/24", "xx-1-arin")], "rir_delegated")

        got = await lookup_ip_org_v2(test_db, "10.1.2.55")
        assert got is not None
        assert got["organization"] == "acme widgets"
        assert got["classification"] == "registered_operator"
        assert got["confidence"] == pytest.approx(0.60)  # 0.45 + 0.15 exact
        assert "registered_holder" in got["relationship_types"]

    async def test_a_sub_delegated_prefix_classifies_as_operational_customer(
        self, test_db
    ):
        from apps.api.services.ip_org_lookup import lookup_ip_org_v2

        await _seed(test_db, [_row("10.1.2.0/24", 64500, "transit isp")], "caida_pfx2as")
        # 10.1.0.0/16, NOT 10.0.0.0/16 — the latter spans only 10.0.0.0-10.0.255.255
        # and never covers 10.1.2.55. Announced /24 is 8 bits more specific.
        await _seed(test_db, [_rir_row("10.1.0.0/16", "xx-1-arin")], "rir_delegated")

        got = await lookup_ip_org_v2(test_db, "10.1.2.55")
        assert got is not None
        assert got["classification"] == "likely_operational_customer"
        assert got["confidence"] == pytest.approx(0.40)  # 0.45 - 0.05
        assert got["uncertainty"], "a sub-delegated guess must state its doubt"

    async def test_the_most_specific_covering_allocation_wins(self, test_db):
        """A /8 and a /24 both cover; only the /24 describes the announcement."""
        from apps.api.services.ip_org_lookup import lookup_ip_org_v2

        await _seed(test_db, [_row("10.1.2.0/24", 64500, "acme widgets")], "caida_pfx2as")
        await _seed(
            test_db,
            [_rir_row("10.0.0.0/8", "wide-arin"), _rir_row("10.1.2.0/24", "narrow-arin")],
            "rir_delegated",
        )
        got = await lookup_ip_org_v2(test_db, "10.1.2.55")
        assert got["classification"] == "registered_operator"

    async def test_an_rpki_invalid_origin_is_disputed(self, test_db):
        from apps.api.services.ip_org_lookup import lookup_ip_org_v2

        await _seed(test_db, [_row("10.1.2.0/24", 64500, "acme widgets")], "caida_pfx2as")
        await _seed(test_db, [_rir_row("10.1.2.0/24", "xx-1-arin")], "rir_delegated")
        await test_db.execute(
            text(
                "INSERT INTO rpki_roas (id, prefix, asn, max_length) VALUES "
                "(gen_random_uuid(), CAST('10.1.0.0/16' AS cidr), 64999, 24)"
            )
        )
        await test_db.commit()

        got = await lookup_ip_org_v2(test_db, "10.1.2.55")
        assert got is not None
        assert got["classification"] == "disputed_origin"
        assert got["confidence"] == pytest.approx(0.40)  # 0.45 + 0.15 - 0.20

    async def test_v1_results_are_unchanged_after_rir_rows_land(self, test_db):
        """AC2.4 — ``org_kind='registry'`` isolation of D9."""
        await _seed(test_db, [_row("10.1.2.0/24", 64500, "acme widgets")], "caida_pfx2as")
        before = await lookup_ip_org(test_db, "10.1.2.55")

        await _seed(test_db, [_rir_row("10.1.2.0/24", "xx-1-arin")], "rir_delegated")
        after = await lookup_ip_org(test_db, "10.1.2.55")

        assert before == after
        assert after["org_name"] == "acme widgets"


class TestResolverEndToEnd:
    async def test_a_local_hit_writes_a_rir_asn_company_graph_row(
        self, test_db, monkeypatch
    ):
        monkeypatch.setattr(
            company_resolver.settings, "company_graph_enabled", True, raising=False
        )
        await _seed(test_db, [_row("13.107.6.0/24", 8075, "acme widgets", "org")])

        out = await company_resolver._resolve_via_local_ip_org(test_db, "13.107.6.9")
        assert out is None  # no domain until Phase 3 — the company_name is the value

        row = (
            await test_db.execute(
                text(
                    "SELECT source, confidence, company_name FROM company_graph "
                    "WHERE ip = '13.107.6.9'"
                )
            )
        ).first()
        assert row is not None, "expected a write-through row"
        assert row[0] == "rir_asn"
        assert row[1] == pytest.approx(0.45)
        assert row[2] == "acme widgets"

    async def test_a_local_miss_writes_nothing(self, test_db, monkeypatch):
        monkeypatch.setattr(
            company_resolver.settings, "company_graph_enabled", True, raising=False
        )
        await _seed(test_db, [_row("203.0.113.0/24", 1, "someone", "org")])
        assert (
            await company_resolver._resolve_via_local_ip_org(test_db, "198.51.100.4")
            is None
        )
        count = (
            await test_db.execute(text("SELECT count(*) FROM company_graph"))
        ).scalar()
        assert count == 0
