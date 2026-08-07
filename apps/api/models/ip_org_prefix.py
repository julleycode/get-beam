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
- ``domain`` is nullable by design: Phase 1/2 ship org-name-only. Phase 3 fills
  domains via targeted Wikidata extraction or lazy Hunter domain-search.
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
    )

    prefix: Mapped[str] = mapped_column(postgresql.CIDR, nullable=False)
    asn: Mapped[int] = mapped_column(Integer, nullable=False)
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
