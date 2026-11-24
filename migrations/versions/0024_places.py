"""Places

Named places to tell someone roughly where they are, "near Gatitu" (decision
L.4). Their own table, not `areas`: areas name a place to other people under
k-anonymity, while a place is only ever named to the person in it.

Reviewed by hand: reference data with no references to or from accounts, loaded
by `scripts/seed_places.py`. The outline gets a GiST index like `areas.boundary`.

Revision ID: 0024
Revises: 0023
Created: 2026-11-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geography

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_geospatial_table(
        "places",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("level", sa.String(length=20), nullable=False),
        sa.Column("ward", sa.String(length=120), nullable=True),
        sa.Column("sub_county", sa.String(length=120), nullable=True),
        sa.Column("county", sa.String(length=120), nullable=False),
        sa.Column("source", sa.String(length=300), nullable=False),
        sa.Column("confidence", sa.String(length=40), nullable=False),
        sa.Column(
            "boundary",
            Geography(
                geometry_type="MULTIPOLYGON",
                srid=4326,
                dimension=2,
                spatial_index=False,
                from_text="ST_GeogFromText",
                name="geography",
                nullable=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_places")),
    )
    op.create_geospatial_index(
        "idx_places_boundary",
        "places",
        ["boundary"],
        unique=False,
        postgresql_using="gist",
        postgresql_ops={},
    )
    op.create_index(op.f("ix_places_county"), "places", ["county"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_places_county"), table_name="places")
    op.drop_geospatial_index(
        "idx_places_boundary",
        table_name="places",
        postgresql_using="gist",
        column_name="boundary",
    )
    op.drop_geospatial_table("places")
