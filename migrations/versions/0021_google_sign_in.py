"""Google sign-in

Signing up with a Google account instead of a phone number (decision A.1):
Google's ID for the account on `users`, the rule that a live account has a phone
number or a Google account, the Google-account ban list, and the `phone_added`
audit action for an account that adds a number later.

Reviewed by hand: every existing live account has a phone number, so the new
check holds for them, and purged accounts have `deleted_at`. The ban list holds
keyed hashes only, like the phone and device lists.

Revision ID: 0021
Revises: 0020
Created: 2026-11-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUDIT_ACTIONS_BEFORE = (
    "account_created",
    "account_deletion_requested",
    "account_deletion_cancelled",
    "account_purged",
    "data_exported",
    "consent_granted",
    "consent_withdrawn",
    "profile_updated",
    "sessions_revoked",
    "refresh_token_reuse_detected",
    "home_location_set",
    "home_location_changed",
    "location_spoof_suspected",
    "user_blocked",
    "user_unblocked",
    "report_submitted",
    "content_auto_hidden",
    "content_flagged",
    "group_deleted",
    "group_member_removed",
    "group_member_banned",
    "group_member_unbanned",
    "group_role_changed",
    "group_ownership_transferred",
    "group_post_removed",
    "staff_signed_in",
    "staff_sign_in_failed",
    "staff_account_created",
    "staff_account_updated",
    "content_removed",
    "content_restored",
    "report_resolved",
    "user_warned",
    "user_suspended",
    "user_unsuspended",
    "user_banned",
    "user_unbanned",
    "user_restricted",
    "user_unrestricted",
    "badge_awarded",
    "badge_revoked",
    "phone_banned",
    "phone_unbanned",
    "device_banned",
    "device_unbanned",
)
AUDIT_ACTIONS_AFTER = (*AUDIT_ACTIONS_BEFORE, "phone_added")

CAN_SIGN_IN = "deleted_at IS NOT NULL OR phone_number IS NOT NULL OR google_sub IS NOT NULL"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _replace_check(table: str, suffix: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{suffix}"), table, type_="check")
    op.create_check_constraint(suffix, table, condition)


def upgrade() -> None:
    op.add_column("users", sa.Column("google_sub", sa.String(length=255), nullable=True))
    op.create_unique_constraint(op.f("uq_users_google_sub"), "users", ["google_sub"])
    op.create_check_constraint("user_can_sign_in", "users", CAN_SIGN_IN)

    op.create_table(
        "banned_google_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("google_hash", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=True),
        sa.Column("staff_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["staff_id"],
            ["staff_accounts.id"],
            name=op.f("fk_banned_google_accounts_staff_id_staff_accounts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_banned_google_accounts_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_banned_google_accounts")),
        sa.UniqueConstraint("google_hash", name=op.f("uq_banned_google_accounts_google_hash")),
    )
    op.create_index(
        op.f("ix_banned_google_accounts_user_id"),
        "banned_google_accounts",
        ["user_id"],
        unique=False,
    )

    _replace_check("audit_events", "audit_action", _in("action", AUDIT_ACTIONS_AFTER))


def downgrade() -> None:
    # Fails while any `phone_added` event exists, as 0013's does for staff
    # actions: the audit log is evidence, and a downgrade doesn't delete it.
    _replace_check("audit_events", "audit_action", _in("action", AUDIT_ACTIONS_BEFORE))

    op.drop_index(op.f("ix_banned_google_accounts_user_id"), table_name="banned_google_accounts")
    op.drop_table("banned_google_accounts")

    # Accounts that signed up with Google and never added a number cannot be
    # represented without the column; this downgrade is for development only.
    op.drop_constraint(op.f("ck_users_user_can_sign_in"), "users", type_="check")
    op.drop_constraint(op.f("uq_users_google_sub"), "users", type_="unique")
    op.drop_column("users", "google_sub")
