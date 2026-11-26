"""Hourly counts of where app users are

God's view can show where app users are now and at different times (decision
D.9). `presence_counts` keeps, per hour and hexagon (resolutions 8, 7, 6), how
many active app users were there: counts only, no account, kept for
`PRESENCE_RETENTION_DAYS` (a year).

Revision ID: 0029
Revises: 0028
Created: 2026-11-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "presence_counts",
        sa.Column("hour_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolution", sa.SmallInteger(), nullable=False),
        sa.Column("cell", sa.BigInteger(), nullable=False),
        sa.Column("people", sa.Integer(), nullable=False),
        sa.CheckConstraint("people > 0", name=op.f("ck_presence_counts_presence_people_positive")),
        sa.CheckConstraint(
            "resolution IN (6, 7, 8)", name=op.f("ck_presence_counts_presence_resolution_known")
        ),
        sa.PrimaryKeyConstraint(
            "hour_start", "resolution", "cell", name=op.f("pk_presence_counts")
        ),
    )
    op.create_index(
        "ix_presence_counts_resolution_hour_start",
        "presence_counts",
        ["resolution", "hour_start"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_presence_counts_resolution_hour_start", table_name="presence_counts")
    op.drop_table("presence_counts")
