// Dates in Nairobi time, and the words the screens use.

const TIME_ZONE = "Africa/Nairobi";

const dateTime = new Intl.DateTimeFormat("en-GB", {
  timeZone: TIME_ZONE,
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});
const dayOnly = new Intl.DateTimeFormat("en-GB", {
  timeZone: TIME_ZONE,
  day: "numeric",
  month: "short",
});

/** "26 Nov 2026, 14:05", in Nairobi time. */
export function when(iso: string | null | undefined): string {
  return iso ? dateTime.format(new Date(iso)) : "—";
}

/** "26 Nov", for a date the API already gave in Nairobi time ("2026-11-26"). */
export function day(isoDate: string): string {
  const [year, month, date] = isoDate.split("-").map(Number);
  // Noon UTC is the same calendar day in Nairobi.
  return dayOnly.format(new Date(Date.UTC(year, month - 1, date, 12)));
}

/** "3 h", "2 days": how long something has waited. */
export function waited(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "—";
  const minutes = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 60_000));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h`;
  return `${Math.round(hours / 24)} days`;
}

export function words(value: string): string {
  const text = value.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export const TARGET_LABELS: Record<string, string> = {
  post: "Post",
  comment: "Comment",
  story: "Story",
  user: "Profile",
  message: "Message",
  review: "Review",
  listing: "Listing",
  service_post: "Service",
  event: "Event",
  group: "Group",
};

export const STATUS_LABELS: Record<string, string> = {
  active: "Active",
  suspended: "Suspended",
  banned: "Banned",
  deletion_pending: "Deleting",
};

/** What set a radius, as the overview explains it. */
export const LIMIT_LABELS: Record<string, string> = {
  users: "Needed more people",
  posts: "Needed more recent posts",
  both: "Needed both",
  floor: "Enough at the smallest radius",
  ceiling: "Short of both at the largest radius",
};

export function shortId(id: string | null | undefined): string {
  return id ? id.slice(0, 8) : "—";
}
