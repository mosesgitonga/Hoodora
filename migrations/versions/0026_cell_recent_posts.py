"""Cells count their recent posts

Decision T.2: the feed radius grows until it holds enough active users and
enough recent posts. `cell_activity` gains `recent_post_count`, the feed posts
placed in the cell within `FEED_RECENT_POST_DAYS`, at most
`FEED_MAX_POSTS_PER_AUTHOR` per author. `refresh_cell_activity` fills it every
15 minutes, so existing rows start at 0 and are counted on the next run.

A count only, like the user counts beside it: nothing about who posted.

Revision ID: 0026
Revises: 0025
Created: 2026-11-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cell_activity",
        sa.Column("recent_post_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_cell_activity_cell_activity_recent_posts_non_negative"),
        "cell_activity",
        "recent_post_count >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_cell_activity_cell_activity_recent_posts_non_negative"),
        "cell_activity",
        type_="check",
    )
    op.drop_column("cell_activity", "recent_post_count")
