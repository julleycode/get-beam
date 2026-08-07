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


def _row(prefix: str, asn: int, org: str, kind: str = "org") -> dict:
    return {
        "prefix": prefix,
        "asn": asn,
        "org_name": org,
        "org_name_raw": org,
        "org_kind": kind,
    }


async def _seed(db, rows: list[dict]) -> None:
    for r in rows:
        await db.execute(
            text(
                "INSERT INTO ip_org_prefixes "
                "(id, prefix, asn, org_name, org_name_raw, org_kind, source) "
                "VALUES (gen_random_uuid(), CAST(:prefix AS cidr), :asn, "
                ":org_name, :org_name_raw, :org_kind, 'test')"
            ),
            r,
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
        from apps.api.services.ip_org_ingest import _load_staging_and_swap

        await _seed(test_db, [_row("10.0.0.0/8", 111, "old org", "org")])
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
        assert not any(n.startswith("ip_org_prefixes_staging") for n in idx)


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
