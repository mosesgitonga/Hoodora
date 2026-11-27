"""Polls on posts, and how many people saw a post

Decision F.1:

- **`post_polls`, `post_poll_options`:** a post may ask a question with 2 to 4
  answers, each with a running count.
- **`post_poll_votes`:** that someone voted, and nothing else. There is no
  option column, so nobody can say how anyone voted.
- **`posts.view_count`:** distinct people who saw the post, the author not
  counted. Counted in Redis with a HyperLogLog, which keeps no list of viewers,
  and copied here each minute.

Revision ID: 0031
Revises: 0030
Created: 2026-11-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "posts", sa.Column("view_count", sa.Integer(), server_default="0", nullable=False)
    )
    op.create_check_constraint("post_view_count_non_negative", "posts", "view_count >= 0")

    op.create_table(
        "post_polls",
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("vote_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "vote_count >= 0", name=op.f("ck_post_polls_poll_vote_count_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["post_id"], ["posts.id"], name=op.f("fk_post_polls_post_id_posts"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("post_id", name=op.f("pk_post_polls")),
    )
    op.create_table(
        "post_poll_options",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("text", sa.String(length=80), nullable=False),
        sa.Column("vote_count", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "position >= 0 AND position < 4",
            name=op.f("ck_post_poll_options_poll_option_position_in_range"),
        ),
        sa.CheckConstraint(
            "vote_count >= 0", name=op.f("ck_post_poll_options_poll_option_vote_count_non_negative")
        ),
        sa.CheckConstraint(
            "length(text) > 0", name=op.f("ck_post_poll_options_poll_option_text_not_empty")
        ),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["post_polls.post_id"],
            name=op.f("fk_post_poll_options_post_id_post_polls"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_post_poll_options")),
        sa.UniqueConstraint(
            "post_id", "position", name=op.f("uq_post_poll_options_post_id_position")
        ),
    )
    op.create_index(
        op.f("ix_post_poll_options_post_id"), "post_poll_options", ["post_id"], unique=False
    )
    op.create_table(
        "post_poll_votes",
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["post_polls.post_id"],
            name=op.f("fk_post_poll_votes_post_id_post_polls"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_post_poll_votes_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("post_id", "user_id", name=op.f("pk_post_poll_votes")),
    )
    op.create_index(
        op.f("ix_post_poll_votes_user_id"), "post_poll_votes", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_post_poll_votes_user_id"), table_name="post_poll_votes")
    op.drop_table("post_poll_votes")
    op.drop_index(op.f("ix_post_poll_options_post_id"), table_name="post_poll_options")
    op.drop_table("post_poll_options")
    op.drop_table("post_polls")
    op.drop_constraint(op.f("ck_posts_post_view_count_non_negative"), "posts", type_="check")
    op.drop_column("posts", "view_count")
