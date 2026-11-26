// The one way the dashboard talks to /v1/admin.
//
// The staff token lives in this module's memory and nowhere else: never
// localStorage, sessionStorage, a cookie or the URL (decision D.1). Reloading the
// page loses it, which signs the person out; that is the intended trade.

import { config } from "./config";

let token: string | null = null;

export function setToken(value: string | null): void {
  token = value;
}

export function hasToken(): boolean {
  return token !== null;
}

export type SignOutReason = "signed_out" | "idle" | "expired";

type Listener = (reason: SignOutReason) => void;
const listeners = new Set<Listener>();

/** Called whenever the session ends, for whatever reason. */
export function onSessionEnded(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function endSession(reason: SignOutReason): void {
  const hadToken = token !== null;
  token = null;
  if (hadToken) listeners.forEach((listener) => listener(reason));
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly code: string | null = null,
    readonly details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** What Refine reads to decide whether an error means "signed out". */
  get statusCode(): number {
    return this.status;
  }
}

export interface RequestOptions {
  body?: unknown;
  query?: Record<string, string | number | undefined | null>;
  /** False only for signing in. */
  auth?: boolean;
}

export const ADMIN_PREFIX = "/v1/admin";

export async function request<T>(
  method: string,
  path: string,
  { body, query, auth = true }: RequestOptions = {},
): Promise<T> {
  const url = new URL(config.apiBaseUrl + ADMIN_PREFIX + path);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, String(value));
  }
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (auth && token) headers.Authorization = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "omit",
      cache: "no-store",
      referrerPolicy: "no-referrer",
    });
  } catch {
    throw new ApiError(0, "Couldn't reach Hoodora. Check your connection and try again.", "network");
  }

  if (response.status === 401 && auth) {
    // Expired, signed out elsewhere, or disabled: in every case, start again.
    endSession("expired");
    throw new ApiError(401, "Your session has ended. Sign in again.", "unauthenticated");
  }
  if (!response.ok) {
    let message = "Something went wrong. Try again.";
    let code: string | null = null;
    let details: Record<string, unknown> = {};
    try {
      const envelope = (await response.json()) as {
        error?: { code?: string; message?: string; details?: Record<string, unknown> };
      };
      message = envelope.error?.message ?? message;
      code = envelope.error?.code ?? null;
      details = envelope.error?.details ?? {};
    } catch {
      // Not the API's envelope (a proxy's error page, say): keep the plain message.
    }
    throw new ApiError(response.status, message, code, details);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
