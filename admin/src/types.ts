// The admin API's shapes, as /v1/admin returns them. Enums come from the API's
// own OpenAPI schema.

export type StaffRole = "moderator" | "admin";

export interface Staff {
  id: string;
  email: string;
  display_name: string;
  role: StaffRole;
  disabled: boolean;
  locked: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface SignInOut {
  access_token: string;
  token_type: string;
  expires_at: string;
  staff: Staff;
}

export interface IssuedCredentials {
  staff: Staff;
  temporary_password: string;
  totp_secret: string;
  totp_uri: string;
}

export type UserStatus = "active" | "suspended" | "banned" | "deletion_pending";

export interface Account {
  id: string;
  display_name: string;
  status: UserStatus;
  created_at: string;
  is_verified_neighbour: boolean;
  badge_locked: boolean;
  restricted: boolean;
  restricted_until: string | null;
  restriction_reason: string | null;
  suspended_until: string | null;
  deleted: boolean;
}

export const REPORT_REASONS = [
  "spam",
  "scam",
  "job_scam",
  "harassment",
  "hate_speech",
  "violence",
  "sexual_content",
  "prohibited_item",
  "impersonation",
  "misinformation",
  "other",
] as const;
export type ReportReason = (typeof REPORT_REASONS)[number];

export const TARGET_TYPES = [
  "post",
  "comment",
  "story",
  "user",
  "message",
  "review",
  "listing",
  "service_post",
  "event",
  "group",
] as const;
export type TargetType = (typeof TARGET_TYPES)[number];

export type ReportStatus = "pending" | "upheld" | "dismissed";

export interface QueueItem {
  target_type: TargetType;
  target_id: string;
  priority: number;
  waiting_since: string;
  report_count: number;
  trusted_report_count: number;
  reasons: ReportReason[];
  held: boolean;
  excerpt: string;
  author: Account | null;
}

export interface Report {
  id: string;
  reporter_id: string;
  reason: ReportReason;
  details: string | null;
  trusted: boolean;
  status: ReportStatus;
  created_at: string;
  resolved_at: string | null;
  resolution_note: string | null;
}

export interface ImageVariant {
  width: number;
  height: number;
  url: string;
}

export interface Content {
  target_type: TargetType;
  target_id: string;
  status: string;
  text: string;
  created_at: string | null;
  images: { media_id: string; variants: Record<string, ImageVariant> }[];
  details: Record<string, unknown>;
  author: Account | null;
}

export interface ContentDetail {
  content: Content;
  reports: Report[];
}

export interface ActionOut {
  reports_resolved: number;
}

export interface Warning {
  id: string;
  reason: string;
  report_id: string | null;
  staff_id: string | null;
  created_at: string;
}

export const AUDIT_ACTIONS = [
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
  "user_looked_up",
  "people_map_viewed",
] as const;

export interface AuditEvent {
  id: string;
  actor_type: "user" | "moderator" | "system";
  actor_id: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  context: Record<string, unknown>;
  request_id: string | null;
  created_at: string;
}

export interface UserHistory {
  account: Account;
  reports_against: Report[];
  reports_by: Report[];
  warnings: Warning[];
  actions: AuditEvent[];
  content_removed_count: number;
}

export interface BanEntry {
  id: string;
  user_id: string | null;
  reason: string | null;
  staff_id: string | null;
  created_at: string;
}

export interface CursorPage<T> {
  items: T[];
  next_cursor: string | null;
}

export interface DayCounts {
  date: string;
  sign_ups: number;
  posts: number;
  listings: number;
  reports_opened: number;
  reports_resolved: number;
}

export interface Stats {
  generated_at: string;
  timezone: string;
  days: DayCounts[];
  totals: {
    users: number;
    active: { last_day: number; last_7_days: number; last_14_days: number; last_30_days: number };
    open_reports: number;
    held_items: number;
    waiting: number;
    oldest_open_report_at: string | null;
    oldest_waiting_since: string | null;
  };
  radius: {
    people: number;
    bands: { from_km: number; to_km: number; people: number }[];
    by_condition: Record<string, number>;
  };
}
