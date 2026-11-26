"""Who may call each admin route (decision D.4).

The routers enforce this through their dependencies (`CurrentStaff` for any staff
member, `AdminStaff` for admins). This table says the same thing in one place, so
it can be read, shown to the dashboard's authors, and checked: a test calls
every `/v1/admin` route with no token, a user's token, a moderator's and an
admin's, and expects exactly what this table says. A route missing from it fails
that test.

`None` means no staff token is needed: signing in.
"""

from __future__ import annotations

from typing import Final

from app.modules.staff.models import StaffRole

MOD = StaffRole.moderator
ADMIN = StaffRole.admin

MINIMUM_ROLE: Final[dict[tuple[str, str], StaffRole | None]] = {
    # Signing in and out, and one's own account.
    ("POST", "/v1/admin/auth/sign-in"): None,
    ("POST", "/v1/admin/auth/sign-out"): MOD,
    ("GET", "/v1/admin/me"): MOD,
    ("POST", "/v1/admin/me/password"): MOD,
    # The queue and the content in it.
    ("GET", "/v1/admin/queue"): MOD,
    ("GET", "/v1/admin/content/{target_type}/{target_id}"): MOD,
    ("POST", "/v1/admin/content/{target_type}/{target_id}/remove"): MOD,
    ("POST", "/v1/admin/content/{target_type}/{target_id}/restore"): MOD,
    ("POST", "/v1/admin/content/{target_type}/{target_id}/resolve"): MOD,
    # People.
    ("POST", "/v1/admin/users/lookup"): MOD,
    ("GET", "/v1/admin/users/{user_id}"): MOD,
    ("POST", "/v1/admin/users/{user_id}/warn"): MOD,
    ("POST", "/v1/admin/users/{user_id}/suspend"): MOD,
    ("POST", "/v1/admin/users/{user_id}/unsuspend"): MOD,
    ("POST", "/v1/admin/users/{user_id}/restrict"): MOD,
    ("POST", "/v1/admin/users/{user_id}/unrestrict"): MOD,
    ("POST", "/v1/admin/users/{user_id}/badge/revoke"): MOD,
    ("POST", "/v1/admin/users/{user_id}/badge/unlock"): MOD,
    ("POST", "/v1/admin/users/{user_id}/ban"): ADMIN,
    ("POST", "/v1/admin/users/{user_id}/unban"): ADMIN,
    # The record and the ban lists.
    ("GET", "/v1/admin/audit"): ADMIN,
    ("GET", "/v1/admin/bans/phones"): ADMIN,
    ("POST", "/v1/admin/bans/phones"): ADMIN,
    ("DELETE", "/v1/admin/bans/phones/{ban_id}"): ADMIN,
    ("GET", "/v1/admin/bans/devices"): ADMIN,
    ("DELETE", "/v1/admin/bans/devices/{ban_id}"): ADMIN,
    # Staff, and the overview.
    ("GET", "/v1/admin/staff"): ADMIN,
    ("POST", "/v1/admin/staff"): ADMIN,
    ("PATCH", "/v1/admin/staff/{staff_id}"): ADMIN,
    ("POST", "/v1/admin/staff/{staff_id}/reset-credentials"): ADMIN,
    ("GET", "/v1/admin/stats"): ADMIN,
}
