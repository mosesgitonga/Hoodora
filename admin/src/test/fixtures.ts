import type { Account, AuditEvent, BanEntry, ContentDetail, QueueItem, Stats, UserHistory } from "../types";
import { staff } from "./harness";

export function account(overrides: Partial<Account> = {}): Account {
  return {
    id: "u1",
    display_name: "Kamau Njoroge",
    status: "active",
    created_at: "2026-10-01T08:00:00Z",
    is_verified_neighbour: false,
    badge_locked: false,
    restricted: false,
    restricted_until: null,
    restriction_reason: null,
    suspended_until: null,
    deleted: false,
    ...overrides,
  };
}

export const queueItem = (overrides: Partial<QueueItem> = {}): QueueItem => ({
  target_type: "post",
  target_id: "p1",
  priority: 20,
  waiting_since: "2026-11-26T05:00:00Z",
  report_count: 2,
  trusted_report_count: 1,
  reasons: ["spam"],
  held: false,
  excerpt: "Cheap phones, send M-Pesa first",
  author: account(),
  ...overrides,
});

export const contentDetail = (overrides: Partial<ContentDetail["content"]> = {}, reports = true): ContentDetail => ({
  content: {
    target_type: "post",
    target_id: "p1",
    status: "visible",
    text: "Cheap phones, send M-Pesa first",
    created_at: "2026-11-25T10:00:00Z",
    images: [],
    details: {},
    author: account(),
    ...overrides,
  },
  reports: reports
    ? [
        {
          id: "r1",
          reporter_id: "u9",
          reason: "spam",
          details: "Same post in every group",
          trusted: true,
          status: "pending",
          created_at: "2026-11-26T05:00:00Z",
          resolved_at: null,
          resolution_note: null,
        },
      ]
    : [],
});

export const history = (overrides: Partial<Account> = {}, empty = false): UserHistory => ({
  account: account(overrides),
  reports_against: empty ? [] : contentDetail().reports,
  reports_by: [],
  warnings: empty ? [] : [{ id: "w1", reason: "Please keep it civil", report_id: null, staff_id: "s-mod", created_at: "2026-11-20T09:00:00Z" }],
  actions: [],
  content_removed_count: empty ? 0 : 1,
});

export const banEntry = (overrides: Partial<BanEntry> = {}): BanEntry => ({
  id: "b1000000-0000-0000-0000-000000000000",
  user_id: "u1",
  reason: "Scam calls",
  staff_id: "s-admin",
  created_at: "2026-11-20T09:00:00Z",
  ...overrides,
});

export const auditEvent = (overrides: Partial<AuditEvent> = {}): AuditEvent => ({
  id: "a1",
  actor_type: "moderator",
  actor_id: "s-mod",
  action: "content_removed",
  target_type: "post",
  target_id: "p1",
  context: { reason: "Scam" },
  request_id: null,
  created_at: "2026-11-26T06:00:00Z",
  ...overrides,
});

export const staffList = () => [staff("admin"), staff("moderator")];

export function stats(overrides: Partial<Stats> = {}): Stats {
  const days = Array.from({ length: 30 }, (_, i) => ({
    date: `2026-${i < 4 ? "10" : "11"}-${String(i < 4 ? 28 + i : i - 3).padStart(2, "0")}`,
    sign_ups: i === 29 ? 7 : 1,
    posts: i === 29 ? 41 : 10,
    listings: 2,
    reports_opened: 1,
    reports_resolved: 1,
  }));
  return {
    generated_at: "2026-11-26T06:00:00Z",
    timezone: "Africa/Nairobi",
    days,
    totals: {
      users: 1200,
      active: { last_day: 300, last_7_days: 700, last_14_days: 850, last_30_days: 1000 },
      open_reports: 4,
      held_items: 2,
      waiting: 5,
      oldest_open_report_at: "2026-11-25T06:00:00Z",
      oldest_waiting_since: "2026-11-24T06:00:00Z",
    },
    radius: {
      people: 850,
      bands: [
        { from_km: 1, to_km: 1, people: 0 },
        { from_km: 1, to_km: 3, people: 600 },
        { from_km: 3, to_km: 5, people: 200 },
        { from_km: 5, to_km: 10, people: 50 },
        { from_km: 10, to_km: 15, people: 0 },
        { from_km: 15, to_km: 15, people: 0 },
      ],
      by_condition: { users: 700, posts: 100, both: 50, floor: 0, ceiling: 0 },
    },
    ...overrides,
  };
}
