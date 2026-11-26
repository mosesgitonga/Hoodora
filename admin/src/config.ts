// Build settings, read once. See .env.example.

function minutes(value: string | undefined, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

export const config = {
  /** The API, without a trailing slash. */
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(/\/+$/, ""),
  /** Sign out after this long without activity. */
  idleTimeoutMinutes: minutes(import.meta.env.VITE_IDLE_TIMEOUT_MINUTES, 15),
};

/** The nonce nginx gave this page, for Ant Design's runtime styles (decision D.5). */
export function cspNonce(): string | undefined {
  const value = document.querySelector('meta[name="csp-nonce"]')?.getAttribute("content");
  return value && value !== "__CSP_NONCE__" ? value : undefined;
}
