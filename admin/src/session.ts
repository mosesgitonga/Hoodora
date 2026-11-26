// Who is signed in, and the idle timer. Memory only, like the token.

import { ApiError, endSession, hasToken, onSessionEnded, request, setToken, type SignOutReason } from "./api";
import { config } from "./config";
import type { SignInOut, Staff } from "./types";

let staff: Staff | null = null;
let lastReason: SignOutReason | null = null;

onSessionEnded((reason) => {
  staff = null;
  lastReason = reason;
  stopIdleWatch();
});

export function currentStaff(): Staff | null {
  return hasToken() ? staff : null;
}

export function isAdmin(): boolean {
  return currentStaff()?.role === "admin";
}

/** Why the last session ended; the sign-in screen says so. Forgotten at the
 * next sign-in, or when the person signed out on purpose. */
export function signOutReason(): SignOutReason | null {
  return lastReason;
}

/** The API answers every failure the same way, and so does this. */
export const SIGN_IN_FAILED = "Those details are not right. Check them and try again.";

export async function signIn(email: string, password: string, code: string): Promise<Staff> {
  try {
    const out = await request<SignInOut>(
      "POST",
      "/auth/sign-in",
      { body: { email: email.trim(), password, code: code.trim() }, auth: false },
    );
    setToken(out.access_token);
    staff = out.staff;
    lastReason = null;
    startIdleWatch(config.idleTimeoutMinutes);
    return out.staff;
  } catch (error) {
    if (error instanceof ApiError && error.code === "network") throw error;
    throw new ApiError(error instanceof ApiError ? error.status : 0, SIGN_IN_FAILED);
  }
}

export async function signOut(reason: SignOutReason = "signed_out"): Promise<void> {
  if (!hasToken()) return;
  try {
    // Ends the server's session too, so the token is dead even if it leaked.
    await request("POST", "/auth/sign-out");
  } catch {
    // Already gone, or offline: the token is forgotten either way.
  }
  endSession(reason);
}

// ---------------------------------------------------------------------------
// Idle timeout (decision D.1)
// ---------------------------------------------------------------------------
const ACTIVITY = ["pointerdown", "keydown", "wheel", "touchstart", "scroll"] as const;
let timer: ReturnType<typeof setTimeout> | null = null;
let idleMs = 0;

function reset(): void {
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => void signOut("idle"), idleMs);
}

export function startIdleWatch(minutes: number): void {
  stopIdleWatch();
  idleMs = minutes * 60_000;
  ACTIVITY.forEach((event) => window.addEventListener(event, reset, { passive: true, capture: true }));
  reset();
}

export function stopIdleWatch(): void {
  if (timer) clearTimeout(timer);
  timer = null;
  ACTIVITY.forEach((event) => window.removeEventListener(event, reset, { capture: true }));
}
