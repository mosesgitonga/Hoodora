"""Zone days

Posting in a place needs days spent there (decision L.2): `user_zone_days`, which
zones (H3 res 7) someone was in on each of the last seven days, as seven bits per
zone. `users.home_claimed_at_signup` for the sign-up shortcut, and
`conversations.request_sender_new_to_area` for the marker on message requests.

Reviewed by hand: existing accounts whose home is confirmed, never moved, and
who have a verified phone get the shortcut, as if they had answered the new
sign-up question. Everyone else starts with no days recorded.

Revision ID: 0022
Revises: 0021
Created: 2026-11-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_zone_days",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("zone", sa.BigInteger(), nullable=False),
        sa.Column("days_mask", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_on", sa.Date(), nullable=False),
        sa.CheckConstraint(
            "days_mask >= 0 AND days_mask < 128",
            name=op.f("ck_user_zone_days_user_zone_days_mask_is_7_bits"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_zone_days_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "zone", name=op.f("pk_user_zone_days")),
    )
    op.create_index("ix_user_zone_days_updated_on", "user_zone_days", ["updated_on"], unique=False)

    op.add_column(
        "users",
        sa.Column(
            "home_claimed_at_signup",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE users SET home_claimed_at_signup = true
        WHERE deleted_at IS NULL
          AND home_cell_res9 IS NOT NULL
          AND NOT home_provisional
          AND home_changed_at IS NULL
          AND phone_verified_at IS NOT NULL
        """
    )

    op.add_column(
        "conversations",
        sa.Column(
            "request_sender_new_to_area",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("conversations", "request_sender_new_to_area")
    op.drop_column("users", "home_claimed_at_signup")
    op.drop_index("ix_user_zone_days_updated_on", table_name="user_zone_days")
    op.drop_table("user_zone_days")
