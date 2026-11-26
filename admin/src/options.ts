// What signing in asks for (decision D.7): the authenticator code can be turned
// off on the server (`STAFF_TOTP_REQUIRED`). Asked once, before anyone signs in.

import { useEffect, useState } from "react";

import { request } from "./api";

let cached: boolean | null = null;

/** Whether the code is required. If the answer can't be had, it is: the form
 * then asks for a code, and a server with codes off simply ignores it. */
export async function codeRequired(): Promise<boolean> {
  if (cached !== null) return cached;
  try {
    const out = await request<{ authenticator_code_required: boolean }>("GET", "/auth/options", { auth: false });
    cached = out.authenticator_code_required !== false;
    return cached;
  } catch {
    return true;
  }
}

/** Null until known. */
export function useCodeRequired(): boolean | null {
  const [required, setRequired] = useState<boolean | null>(cached);
  useEffect(() => {
    let live = true;
    void codeRequired().then((value) => {
      if (live) setRequired(value);
    });
    return () => {
      live = false;
    };
  }, []);
  return required;
}

/** For tests: forget the answer. */
export function resetOptions(): void {
  cached = null;
}
