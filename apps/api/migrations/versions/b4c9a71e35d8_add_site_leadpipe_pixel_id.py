"""add leadpipe_pixel_id to sites

A Leadpipe pixel is bound 1-1 to a domain — ``POST /v1/data/pixels`` answers
409 "Pixel already exists for this domain" on a duplicate. Until now Beam had
no per-site place to keep that id, so every site was served ONE shared pixel id
from env (``LEADPIPE_DEFAULT_PIXEL_ID``). That id belongs to a single domain, so
on every other site the tag loaded, collected nothing, and left
``GET /v1/data?domain=<that site>`` empty forever while looking installed.

This column is what lets a site carry its OWN pixel, provisioned on demand when
the install snippet is first requested.

Additive and reversible: one nullable column, no index (lookups are by
``site_id``, which is already unique), no constraint, no backfill — existing
rows keep NULL and provision on their next snippet fetch.

Revision ID: b4c9a71e35d8
Revises: a7d419e6c052
Create Date: 2026-08-06

"""
from alembic import op
import sqlalchemy as sa

revision = "b4c9a71e35d8"
down_revision = "a7d419e6c052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sites",
        sa.Column("leadpipe_pixel_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sites", "leadpipe_pixel_id")
