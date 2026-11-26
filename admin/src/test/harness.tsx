// A mocked admin API and a way to render the whole app at a path.

import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";

import { App } from "../App";
import { config } from "../config";
import { signIn } from "../session";
import type { Staff, StaffRole } from "../types";

export type Reply = { status: number; body?: unknown };
export type Handler = (body: unknown, url: URL) => Reply;

export interface Call {
  method: string;
  path: string;
  url: URL;
  body: unknown;
  headers: Record<string, string>;
}

export const TOKEN = "staff-token-abc123";

export function staff(role: StaffRole, overrides: Partial<Staff> = {}): Staff {
  return {
    id: role === "admin" ? "s-admin" : "s-mod",
    email: `${role}@hoodora.test`,
    display_name: role === "admin" ? "Wanjiru Admin" : "Otieno Moderator",
    role,
    disabled: false,
    locked: false,
    last_login_at: null,
    created_at: "2026-11-01T08:00:00Z",
    ...overrides,
  };
}

export function apiError(status: number, message: string, code = "error"): Reply {
  return { status, body: { error: { code, message, details: {} } } };
}

/** Routes are "METHOD /path", the path after /v1/admin, without the query. */
export function mockApi(routes: Record<string, Reply | Handler>) {
  const calls: Call[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input));
    const method = (init.method ?? "GET").toUpperCase();
    const body = typeof init.body === "string" ? JSON.parse(init.body) : undefined;
    if (!url.href.startsWith(config.apiBaseUrl + "/v1/admin")) {
      throw new Error(`The app called something other than the admin API: ${url.href}`);
    }
    const path = url.pathname.replace(/^\/v1\/admin/, "");
    calls.push({ method, path, url, body, headers: { ...(init.headers as Record<string, string>) } });
    const route = routes[`${method} ${path}`];
    const reply = typeof route === "function" ? route(body, url) : route;
    if (!reply) return new Response(JSON.stringify({ error: { code: "not_found", message: "Not found" } }), { status: 404 });
    return new Response(reply.status === 204 ? null : JSON.stringify(reply.body ?? {}), {
      status: reply.status,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

export const SIGN_IN = (role: StaffRole): Reply => ({
  status: 200,
  body: { access_token: TOKEN, token_type: "bearer", expires_at: "2026-11-26T18:00:00Z", staff: staff(role) },
});

/** Signed in as `role`, then the app rendered at `path`. */
export async function openAs(role: StaffRole | null, path: string, routes: Record<string, Reply | Handler> = {}) {
  const api = mockApi({ "POST /auth/sign-in": SIGN_IN(role ?? "moderator"), "POST /auth/sign-out": { status: 204 }, ...routes });
  if (role) await signIn("x@hoodora.test", "password", "123456");
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
  return api;
}

export const findText = (text: string | RegExp) => screen.findByText(text, {}, { timeout: 8000 });
