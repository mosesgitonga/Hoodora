"""Staff can look a person up by phone number

The admin dashboard's People screen needs a way in besides an ID (decision D.2).
`POST /v1/admin/users/lookup` finds an account by its phone number, and every
lookup is audited as `user_looked_up`, found or not. The number itself is never
stored in the audit row, only that the lookup was by phone.

The downgrade fails while any `user_looked_up` event exists, as 0013's and
0021's do: the audit log is evidence, and a downgrade doesn't delete it.

Revision ID: 0027
Revises: 0026
Created: 2026-11-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
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
    "phone_added",
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

AUDIT_ACTIONS_AFTER = (*AUDIT_ACTIONS_BEFORE, "user_looked_up")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _replace_check(table: str, suffix: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{suffix}"), table, type_="check")
    op.create_check_constraint(suffix, table, condition)


def upgrade() -> None:
    _replace_check("audit_events", "audit_action", _in("action", AUDIT_ACTIONS_AFTER))


def downgrade() -> None:
    _replace_check("audit_events", "audit_action", _in("action", AUDIT_ACTIONS_BEFORE))
