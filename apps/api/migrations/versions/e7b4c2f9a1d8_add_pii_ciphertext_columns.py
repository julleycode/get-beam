"""add encrypted-PII columns (ciphertext + blind index) — Phase 05 step 5a

Revision ID: e7b4c2f9a1d8
Revises: e6b3c2a9f1d7
Create Date: 2026-06-14

Phase 05 step 5a: add the new columns ONLY. Nothing reads or writes them yet —
this is a safe, no-behavior-change migration. Dual-write (5b), backfill (5c),
and read cutover (5d) come in later, separately-deployed steps.

- *_ciphertext: Fernet-encrypted value of the corresponding plaintext column.
- *_bidx: HMAC blind index of the email, for equality/uniqueness lookups once
  reads cut over (only on searched columns — emails).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "e7b4c2f9a1d8"
down_revision: Union[str, None] = "e6b3c2a9f1d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # visitor_emails
    op.add_column("visitor_emails", sa.Column("email_ciphertext", sa.Text(), nullable=True))
    op.add_column("visitor_emails", sa.Column("email_bidx", sa.String(length=64), nullable=True))
    op.create_index("ix_visitor_emails_email_bidx", "visitor_emails", ["email_bidx"])

    # identified_visitors
    op.add_column("identified_visitors", sa.Column("email_ciphertext", sa.Text(), nullable=True))
    op.add_column("identified_visitors", sa.Column("email_bidx", sa.String(length=64), nullable=True))
    op.add_column("identified_visitors", sa.Column("full_name_ciphertext", sa.Text(), nullable=True))
    op.create_index("ix_identified_visitors_email_bidx", "identified_visitors", ["email_bidx"])

    # beam_identity_graph
    op.add_column("beam_identity_graph", sa.Column("email_ciphertext", sa.Text(), nullable=True))
    op.add_column("beam_identity_graph", sa.Column("email_bidx", sa.String(length=64), nullable=True))
    op.add_column("beam_identity_graph", sa.Column("full_name_ciphertext", sa.Text(), nullable=True))
    op.create_index("ix_beam_identity_graph_email_bidx", "beam_identity_graph", ["email_bidx"])

    # enrichment_profiles (social handles/URLs — ciphertext only, no blind index)
    op.add_column("enrichment_profiles", sa.Column("linkedin_url_ciphertext", sa.Text(), nullable=True))
    op.add_column("enrichment_profiles", sa.Column("twitter_handle_ciphertext", sa.Text(), nullable=True))
    op.add_column("enrichment_profiles", sa.Column("facebook_url_ciphertext", sa.Text(), nullable=True))
    op.add_column("enrichment_profiles", sa.Column("github_url_ciphertext", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("enrichment_profiles", "github_url_ciphertext")
    op.drop_column("enrichment_profiles", "facebook_url_ciphertext")
    op.drop_column("enrichment_profiles", "twitter_handle_ciphertext")
    op.drop_column("enrichment_profiles", "linkedin_url_ciphertext")

    op.drop_index("ix_beam_identity_graph_email_bidx", table_name="beam_identity_graph")
    op.drop_column("beam_identity_graph", "full_name_ciphertext")
    op.drop_column("beam_identity_graph", "email_bidx")
    op.drop_column("beam_identity_graph", "email_ciphertext")

    op.drop_index("ix_identified_visitors_email_bidx", table_name="identified_visitors")
    op.drop_column("identified_visitors", "full_name_ciphertext")
    op.drop_column("identified_visitors", "email_bidx")
    op.drop_column("identified_visitors", "email_ciphertext")

    op.drop_index("ix_visitor_emails_email_bidx", table_name="visitor_emails")
    op.drop_column("visitor_emails", "email_bidx")
    op.drop_column("visitor_emails", "email_ciphertext")
