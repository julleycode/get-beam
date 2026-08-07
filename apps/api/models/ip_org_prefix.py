"""Self-hosted IP prefix → organization table (Pillar 1 of the owned identity core).

Beam resolves company-from-IP via free rDNS first and PAID providers (PDL /
IPinfo, budget-capped) second. Every paid hit is rented data that expires from a
Redis cache. This table makes the IP→company core OWNED: public BGP/WHOIS-derived
snapshots (CAIDA RouteViews ``pfx2as`` for prefix→ASN, CAIDA AS2Org for
ASN→organization) are joined offline and served from Postgres with a ``cidr``
GiST index, so a lookup costs a sub-5ms index scan and zero dollars.

Design notes that are load-bearing:

- ``prefix`` is a real ``CIDR`` column, not a string. The whole point is the
  containment operator (``prefix >>= :ip``), which needs the network type and a
  GiST ``inet_ops`` index. A ``String`` column would silently degrade to a table
  scan and lose the "most specific prefix wins" semantics entirely.
- ``org_kind`` TAGS rather than filters. ISP/eyeball and datacenter prefixes are
  stored, not dropped, so the dataset stays usable for abuse/datacenter work and
  so the lookup's filter policy can change without a full re-ingest. The lookup
  service applies ``org_kind = 'org'``.
- ``domain`` is nullable by design and stays unfilled: org-name → domain mapping
  was split OUT of Phase 3 into a follow-on plan gated on a coverage measurement.
- Phase 3 turns this from a flat prefix→company table into TIME-AWARE EVIDENCE:
  ``relationship_type`` records WHICH relationship a row asserts, so a BGP origin
  (frequently a transit provider announcing on a customer's behalf) is no longer
  confused with a registered holder. Fusion across sources happens in
  ``services/ip_org_fusion.py``, not in this table.
- ``org_name`` is the NORMALIZED join key (legal suffixes stripped, lowercased);
  ``org_name_raw`` keeps the as-published string so a bad join is debuggable.

``id`` / ``created_at`` / ``updated_at`` come from ``Base``.
"""

from datetime import date

from sqlalchemy import Date, Index, Integer, String
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base

#: Table name shared by the model, the migration and the ingest staging swap.
IP_ORG_TABLE = "ip_org_prefixes"
#: Staging twin created (and dropped) at ingest time — never in a migration.
IP_ORG_STAGING_TABLE = "ip_org_prefixes_staging"

#: THE advisory-lock key for every writer of ``ip_org_prefixes`` (D10).
#:
#: Declared here, next to the table it protects, precisely because more than one
#: service now rebuilds this table: the CAIDA refresh (daily) and the RIR
#: delegated-extended refresh (weekly). Both end in ``DROP TABLE`` + ``RENAME``,
#: and both rely on copying the OTHER source's rows into staging first. With two
#: separate keys those schedules can interleave, the carry-over reads a snapshot
#: that goes stale mid-flight, and the RENAME silently discards the other
#: source's freshly loaded rows. One key, one writer at a time.
#:
#: ``rpki_roas`` is a DIFFERENT table with its own writer and deliberately keeps
#: its own key — serializing it here would cost throughput for no safety gain.
IP_ORG_WRITE_LOCK_KEY = "beam_ip_org_ingest"

#: Which relationship an evidence row asserts between a prefix and an org.
#:
#: - ``route_origin``      — BGP says this AS announces the prefix (CAIDA pfx2as).
#: - ``registered_holder`` — an RIR allocated/assigned the range (delegated-extended).
#: - ``rpki_authorizer``   — reserved for name-bearing RPKI-derived evidence.
#:
#: The vocabulary is EXTENSIBLE. Values from the research taxonomy
#: (``network_operator``, ``infrastructure_provider``, ``likely_customer``,
#: ``reverse_dns_owner``) are reserved but not implemented. This is deliberately
#: a Python frozenset and NOT a database enum: adding a relationship must be a
#: code change, never a migration of a million-row hot table.
RELATIONSHIP_TYPES: frozenset[str] = frozenset(
    {"route_origin", "registered_holder", "rpki_authorizer"}
)


class IpOrgPrefix(Base):
    """One announced IP prefix and the organization that owns its ASN."""

    __tablename__ = IP_ORG_TABLE
    __table_args__ = (
        # The containment index. ``inet_ops`` is REQUIRED: the default opclass
        # for a GiST index on cidr does not support ``>>=``, so without it the
        # planner falls back to a sequential scan on ~1M rows.
        Index(
            "idx_ip_org_prefixes_prefix_gist",
            "prefix",
            postgresql_using="gist",
            postgresql_ops={"prefix": "inet_ops"},
        ),
        Index("idx_ip_org_prefixes_asn", "asn"),
        Index("idx_ip_org_prefixes_org_name", "org_name"),
        Index("idx_ip_org_prefixes_relationship_type", "relationship_type"),
    )

    prefix: Mapped[str] = mapped_column(postgresql.CIDR, nullable=False)
    # NULL means this evidence class carries no ASN: an RIR delegated-extended
    # record (``registered_holder``) publishes a range and an opaque handle, and
    # no autonomous-system number at all. Writing a number that is not in the
    # source would be a fabricated fact every future reader must know to
    # special-case; NULL states the same thing checkably.
    asn: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Normalized organization name (join/dedup key).
    org_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # As-published organization name, kept for debugging the ASN→org join.
    org_name_raw: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Filled in Phase 3; nullable until then.
    domain: Mapped[str | None] = mapped_column(String(253), nullable=True)
    # 'org' | 'eyeball' | 'datacenter' | 'cdn' — see classify_org_kind.
    org_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="org")
    # Provenance of the snapshot, e.g. "caida_pfx2as".
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    # Publication date of the snapshot this row came from.
    dataset_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Which relationship this row asserts — see RELATIONSHIP_TYPES. Defaulted so
    # every pre-Phase-3 row reads back as what it actually is: BGP origin data.
    relationship_type: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="route_origin", default="route_origin"
    )
    # Snapshot semantics, not row history (D2): ``valid_from`` is the source
    # snapshot's date and ``valid_to`` is always NULL, meaning "asserted by the
    # current snapshot". A swap replaces a source's rows wholesale, so superseded
    # assertions are dropped rather than closed. ``valid_to`` ships now, unused,
    # so an archive-on-swap history table is an additive change later rather than
    # another migration of this hot table.
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
