"""Validated RPKI Route Origin Authorizations, for BGP origin cross-checking.

An ROA is a signed statement by a prefix HOLDER naming the AS(es) authorized to
announce that prefix. It is the only one of Beam's three evidence sources that
carries cryptographic intent rather than observation: CAIDA says "this AS is
announcing it", the RIR files say "this handle was allocated it", and an ROA
says "the holder authorized this".

**Why this is its own table rather than ``ip_org_prefixes`` evidence rows (D5).**
An ROA authorizes an ASN, not an ORGANIZATION, and carries ``maxLength``, which
has no home in an org-keyed row. Storing it as evidence would force inventing an
``org_name`` for a record that names no organization — a fabricated field, which
is the exact defect class this whole phase exists to remove. So ROAs live here,
and fusion consumes them through ``rpki_validate.validate_origin`` as a
three-state signal instead of as a row.

``max_length`` is load-bearing, not decoration: an ROA for ``10.0.0.0/8`` with
``maxLength 16`` authorizes every announcement from /8 through /16 and forbids a
/24. Dropping the column would make every more-specific announcement look
invalid.

IPv4 only, matching the rest of the pipeline. ``id`` / ``created_at`` /
``updated_at`` come from ``Base``.
"""

from sqlalchemy import BigInteger, Index, Integer
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base

#: Table name shared by the model, the migration and the ingest staging swap.
RPKI_ROA_TABLE = "rpki_roas"
#: Staging twin created (and dropped) at ingest time — never in a migration.
RPKI_ROA_STAGING_TABLE = "rpki_roas_staging"

#: Advisory-lock key for this table's writer. Deliberately DIFFERENT from
#: ``IP_ORG_WRITE_LOCK_KEY`` (D10): this writer never touches
#: ``ip_org_prefixes``, so sharing a key would serialize two independent jobs
#: and cost throughput for no safety gain.
RPKI_WRITE_LOCK_KEY = "beam_rpki_ingest"


class RpkiRoa(Base):
    """One validated ROA: prefix, authorized origin ASN, and max length."""

    __tablename__ = RPKI_ROA_TABLE
    __table_args__ = (
        # Same containment story as ip_org_prefixes: ``inet_ops`` is REQUIRED,
        # because the default GiST opclass for cidr does not support ``>>=`` and
        # the planner would fall back to a sequential scan over ~500k rows on a
        # query that sits inside the live resolver path.
        Index(
            "idx_rpki_roas_prefix_gist",
            "prefix",
            postgresql_using="gist",
            postgresql_ops={"prefix": "inet_ops"},
        ),
    )

    prefix: Mapped[str] = mapped_column(postgresql.CIDR, nullable=False)
    # BIGINT, not INTEGER. Autonomous-system numbers are 32-bit UNSIGNED
    # (RFC 6793), so the top of the space — 4,294,967,294 — overflows a signed
    # int32 by design, and 4-byte ASNs really do appear in published ROAs: the
    # live Cloudflare dump carried 17 of them out of 755,538 IPv4 ROAs.
    #
    # Dropping those rows instead would be actively harmful rather than merely
    # lossy. ``validate_origin`` returns INVALID when a covering ROA exists but
    # none authorizes the announcement — so silently discarding the one
    # authorizing ROA converts a legitimate announcement into a "disputed"
    # verdict, costing it 0.20 confidence and mislabelling it. Storing the real
    # number is the only correct option.
    asn: Mapped[int] = mapped_column(BigInteger, nullable=False)
    max_length: Mapped[int] = mapped_column(Integer, nullable=False)
