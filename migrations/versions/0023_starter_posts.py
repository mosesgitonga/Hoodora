"""Starter posts

Decision L.3: every account may make a few posts, once, somewhere it doesn't yet
have the days, so a newcomer isn't silenced for four days. They replace the
sign-up shortcut of decision L.2, so `users.home_claimed_at_signup` goes, and
`users.starter_posts_used` counts what's been used.

Reviewed by hand: every account starts with none used, existing ones included.

Revision ID: 0023
Revises: 0022
Created: 2026-11-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("starter_posts_used", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        "user_starter_posts_used_non_negative", "users", "starter_posts_used >= 0"
    )
    op.drop_column("users", "home_claimed_at_signup")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "home_claimed_at_signup",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.drop_constraint(
        op.f("ck_users_user_starter_posts_used_non_negative"), "users", type_="check"
    )
    op.drop_column("users", "starter_posts_used")
