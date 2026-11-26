// Refine's providers over the admin API.

import type {
  AccessControlProvider,
  AuthProvider,
  BaseRecord,
  CrudFilters,
  DataProvider,
} from "@refinedev/core";

import { ApiError, hasToken, request } from "./api";
import { config } from "./config";
import { currentStaff, signIn, signOut } from "./session";
import type { CursorPage } from "./types";

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------
export const authProvider: AuthProvider = {
  async login({ email, password, code }: { email: string; password: string; code: string }) {
    try {
      const staff = await signIn(email, password, code);
      return { success: true, redirectTo: staff.role === "admin" ? "/overview" : "/queue" };
    } catch (error) {
      const message = error instanceof Error ? error.message : "Something went wrong.";
      return { success: false, error: { name: "Couldn't sign in", message } };
    }
  },
  async logout() {
    await signOut("signed_out");
    return { success: true, redirectTo: "/sign-in" };
  },
  async check() {
    return hasToken() ? { authenticated: true } : { authenticated: false, redirectTo: "/sign-in" };
  },
  async onError(error: unknown) {
    // The API client has already forgotten the token; this sends the screen away.
    if (error instanceof ApiError && error.status === 401) {
      return { logout: true, redirectTo: "/sign-in" };
    }
    return {};
  },
  async getIdentity() {
    const staff = currentStaff();
    // `name` is what the layout's header shows.
    return staff ? { ...staff, name: `${staff.display_name} · ${staff.role === "admin" ? "Admin" : "Moderator"}` } : null;
  },
  async getPermissions() {
    return currentStaff()?.role ?? null;
  },
};

// ---------------------------------------------------------------------------
// Access: hiding what a role can't do. The server decides; this only keeps
// the screen honest (decision D.4).
// ---------------------------------------------------------------------------
export const ADMIN_RESOURCES = new Set(["overview", "audit", "bans", "staff"]);
export const ADMIN_ACTIONS = new Set(["ban", "unban"]);

export function allowed(role: string | null | undefined, resource?: string, action?: string): boolean {
  if (!role) return false;
  if (role === "admin") return true;
  if (resource && ADMIN_RESOURCES.has(resource)) return false;
  if (action && ADMIN_ACTIONS.has(action)) return false;
  return true;
}

export const accessControlProvider: AccessControlProvider = {
  async can({ resource, action }) {
    const can = allowed(currentStaff()?.role, resource, action);
    return can ? { can } : { can, reason: "That needs an admin." };
  },
  options: { buttons: { enableAccessControl: true, hideIfUnauthorized: true } },
};

// ---------------------------------------------------------------------------
// Data
// ---------------------------------------------------------------------------
const PAGE_SIZE = 25;

function filterValues(filters: CrudFilters | undefined): Record<string, string> {
  const values: Record<string, string> = {};
  for (const filter of filters ?? []) {
    if ("field" in filter && filter.value !== undefined && filter.value !== null && filter.value !== "") {
      values[filter.field] = String(filter.value);
    }
  }
  return values;
}

const LISTS: Record<string, string> = {
  queue: "/queue",
  audit: "/audit",
  "bans/phones": "/bans/phones",
  "bans/devices": "/bans/devices",
  staff: "/staff",
};

export const dataProvider: DataProvider = {
  getApiUrl: () => config.apiBaseUrl,

  async getList({ resource, pagination, filters }) {
    const path = LISTS[resource];
    if (!path) throw new Error(`No list for ${resource}`);
    if (resource === "staff") {
      const data = await request<BaseRecord[]>("GET", path);
      return { data: data as never, total: data.length };
    }
    // The API pages by cursor. Refine hands the last page's `cursor.next` back
    // as the page to fetch; the first page is a number.
    const page = pagination?.currentPage;
    const page_cursor = typeof page === "string" ? page : undefined;
    const out = await request<CursorPage<BaseRecord>>("GET", path, {
      query: { ...filterValues(filters), limit: pagination?.pageSize ?? PAGE_SIZE, cursor: page_cursor },
    });
    return {
      data: out.items as never,
      total: out.items.length,
      cursor: { next: out.next_cursor ?? undefined },
    };
  },

  async getOne({ resource, id }) {
    if (resource === "content") return { data: await request("GET", `/content/${id}`) };
    if (resource === "people") return { data: await request("GET", `/users/${id}`) };
    throw new Error(`No record for ${resource}`);
  },

  async create({ resource, variables }) {
    if (resource === "staff" || resource === "bans/phones") {
      return { data: await request("POST", `/${resource}`, { body: variables }) };
    }
    throw new Error(`Can't create ${resource}`);
  },

  async update({ resource, id, variables }) {
    if (resource === "staff") return { data: await request("PATCH", `/staff/${id}`, { body: variables }) };
    throw new Error(`Can't update ${resource}`);
  },

  async deleteOne({ resource, id }) {
    if (resource === "bans/phones" || resource === "bans/devices") {
      await request("DELETE", `/${resource}/${id}`);
      return { data: { id } as never };
    }
    throw new Error(`Can't delete ${resource}`);
  },

  async custom({ url, method, payload, query }) {
    const data = await request(method.toUpperCase(), url, {
      body: method.toLowerCase() === "get" ? undefined : (payload ?? {}),
      query: query as Record<string, string> | undefined,
    });
    return { data: data as never };
  },
};
