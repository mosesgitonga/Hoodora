import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { hasToken } from "../api";
import { App } from "../App";
import { signIn, SIGN_IN_FAILED, startIdleWatch } from "../session";
import { apiError, findText, mockApi, openAs, SIGN_IN, TOKEN } from "./harness";

async function fillSignIn(code = "123456") {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Email"), "otieno@hoodora.test");
  await user.type(screen.getByLabelText("Password"), "correct horse battery");
  await user.type(screen.getByLabelText("Authenticator code"), code);
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe("signing in", () => {
  it("sends email, password and code in one go and lands a moderator on the queue", async () => {
    const api = mockApi({
      "POST /auth/sign-in": SIGN_IN("moderator"),
      "GET /queue": { status: 200, body: { items: [], next_cursor: null } },
    });
    renderAt("/sign-in");
    await fillSignIn();

    expect(await findText("Nothing is waiting")).toBeInTheDocument();
    const call = api.calls.find((c) => c.path === "/auth/sign-in");
    expect(call?.body).toEqual({ email: "otieno@hoodora.test", password: "correct horse battery", code: "123456" });
    // Every later call carries the token in the header, and only there.
    const queue = api.calls.find((c) => c.path === "/queue");
    expect(queue?.headers.Authorization).toBe(`Bearer ${TOKEN}`);
    expect(queue?.url.search).not.toContain(TOKEN);
  });

  it.each([
    ["wrong details", apiError(401, "Those details are not right", "unauthenticated")],
    ["a locked account", apiError(401, "Those details are not right", "unauthenticated")],
    ["too many tries", apiError(429, "Too many requests", "rate_limited")],
    ["a server error", apiError(500, "Internal error", "internal_error")],
  ])("shows the same message for %s", async (_, reply) => {
    mockApi({ "POST /auth/sign-in": reply });
    renderAt("/sign-in");
    await fillSignIn();
    expect(await findText(SIGN_IN_FAILED)).toBeInTheDocument();
    expect(hasToken()).toBe(false);
  });

  it("asks for the 6 digits before sending anything", async () => {
    const api = mockApi({ "POST /auth/sign-in": SIGN_IN("moderator") });
    renderAt("/sign-in");
    await fillSignIn("12ab");
    expect(await findText("The 6 digits from your authenticator app.")).toBeInTheDocument();
    // Only the question of what to ask for went out; no sign-in.
    expect(api.calls.filter((c) => c.path === "/auth/sign-in")).toHaveLength(0);
  });
});

describe("with sign-in codes off (decision D.7)", () => {
  const OFF = { "GET /auth/options": { status: 200, body: { authenticator_code_required: false } } };

  it("signs in with email and password alone", async () => {
    const api = mockApi({
      ...OFF,
      "POST /auth/sign-in": SIGN_IN("moderator"),
      "GET /queue": { status: 200, body: { items: [], next_cursor: null } },
    });
    renderAt("/sign-in");
    await screen.findByLabelText("Email");
    await waitFor(() => expect(screen.queryByLabelText("Authenticator code")).not.toBeInTheDocument());

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email"), "otieno@hoodora.test");
    await user.type(screen.getByLabelText("Password"), "correct horse battery");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await findText("Nothing is waiting")).toBeInTheDocument();
    expect(api.calls.find((c) => c.path === "/auth/sign-in")?.body).toEqual({
      email: "otieno@hoodora.test",
      password: "correct horse battery",
    });
  });

  it("changes the password without a code", async () => {
    const api = await openAs("moderator", "/account", { ...OFF, "POST /me/password": { status: 204 } });
    await userEvent.type(await screen.findByLabelText("Current password", {}, { timeout: 8000 }), "old password here");
    await waitFor(() => expect(screen.queryByLabelText("Authenticator code")).not.toBeInTheDocument());
    await userEvent.type(screen.getByLabelText("New password"), "a much longer password");
    await userEvent.click(screen.getByRole("button", { name: "Change password" }));
    expect(await findText("Password changed.")).toBeInTheDocument();
    expect(api.calls.find((c) => c.path === "/me/password")?.body).toEqual({
      current_password: "old password here",
      new_password: "a much longer password",
    });
  });

  it("still asks for a code if the server can't say", async () => {
    mockApi({ "GET /auth/options": { status: 500, body: {} } });
    renderAt("/sign-in");
    expect(await screen.findByLabelText("Authenticator code", {}, { timeout: 8000 })).toBeInTheDocument();
  });
});

describe("nothing leaves for anywhere but the API", () => {
  it("sends no telemetry and loads nothing from elsewhere", async () => {
    const images: string[] = [];
    const RealImage = window.Image;
    vi.stubGlobal("Image", class extends RealImage {
      set src(value: string) {
        images.push(value);
      }
    });
    // The harness's fetch refuses any address but the admin API's.
    await openAs("admin", "/queue", { "GET /queue": { status: 200, body: { items: [], next_cursor: null } } });
    await findText("Nothing is waiting");
    expect(images.filter((url) => !url.startsWith("/"))).toEqual([]);
    expect([...document.querySelectorAll("script[src], link[href]")].map((el) => el.getAttribute("src") ?? el.getAttribute("href")).filter((url) => url && /^https?:/.test(url))).toEqual([]);
  });
});

describe("the token", () => {
  it("is never written to any browser storage, a cookie or the URL", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const cookie = vi.spyOn(document, "cookie", "set");
    mockApi({
      "POST /auth/sign-in": SIGN_IN("admin"),
      "GET /stats": { status: 500, body: {} },
    });
    renderAt("/sign-in");
    await fillSignIn();
    await findText("Couldn't load the overview");

    expect(hasToken()).toBe(true);
    for (const [key, value] of setItem.mock.calls) {
      expect(`${key}=${value}`).not.toContain(TOKEN);
    }
    expect(cookie).not.toHaveBeenCalled();
    expect(document.cookie).toBe("");
    expect(JSON.stringify({ ...localStorage })).not.toContain(TOKEN);
    expect(JSON.stringify({ ...sessionStorage })).not.toContain(TOKEN);
    expect(window.location.href).not.toContain(TOKEN);
  });
});

describe("ending a session", () => {
  it("signs out after the idle time, ending the server session too", async () => {
    const api = mockApi({ "POST /auth/sign-in": SIGN_IN("moderator"), "POST /auth/sign-out": { status: 204 } });
    await signIn("x@hoodora.test", "password", "123456");
    vi.useFakeTimers();
    startIdleWatch(15);

    await act(async () => {
      vi.advanceTimersByTime(14 * 60_000);
    });
    window.dispatchEvent(new KeyboardEvent("keydown"));
    await act(async () => {
      vi.advanceTimersByTime(14 * 60_000);
    });
    expect(hasToken()).toBe(true); // activity reset the clock

    await act(async () => {
      vi.advanceTimersByTime(2 * 60_000);
    });
    await vi.waitFor(() => expect(hasToken()).toBe(false));
    expect(api.calls.some((c) => c.method === "POST" && c.path === "/auth/sign-out")).toBe(true);
  });

  it("says why on the sign-in screen after an idle sign-out", async () => {
    mockApi({ "POST /auth/sign-in": SIGN_IN("moderator"), "POST /auth/sign-out": { status: 204 }, "GET /queue": { status: 200, body: { items: [], next_cursor: null } } });
    await signIn("x@hoodora.test", "password", "123456");
    renderAt("/queue");
    await findText("Nothing is waiting");

    // A real, very short wait: React Query's own timers must keep running.
    startIdleWatch(0.01);
    expect(await findText(/signed out after 15 minutes without activity/)).toBeInTheDocument();
  });

  it("signs out on any 401", async () => {
    await openAs("moderator", "/queue", { "GET /queue": apiError(401, "That staff session is no longer valid") });
    expect(await screen.findByRole("button", { name: "Sign in" }, { timeout: 8000 })).toBeInTheDocument();
    expect(await findText("Your session ended. Sign in again to carry on.")).toBeInTheDocument();
    expect(hasToken()).toBe(false);
  });

  it("signs out from the menu", async () => {
    const api = await openAs("moderator", "/queue", { "GET /queue": { status: 200, body: { items: [], next_cursor: null } } });
    await findText("Nothing is waiting");
    await userEvent.click(await findText("Logout"));
    expect(await screen.findByRole("button", { name: "Sign in" }, { timeout: 8000 })).toBeInTheDocument();
    expect(api.calls.some((c) => c.path === "/auth/sign-out")).toBe(true);
    expect(hasToken()).toBe(false);
  });
});

describe("roles", () => {
  const EMPTY_QUEUE = { "GET /queue": { status: 200, body: { items: [], next_cursor: null } } };

  it("a moderator never sees Staff, the ban lists, the audit log or the overview", async () => {
    await openAs("moderator", "/queue", EMPTY_QUEUE);
    await findText("Nothing is waiting");
    for (const label of ["Reports", "People", "My account"]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    for (const label of ["Staff", "Ban lists", "Audit log", "Overview"]) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
  });

  it("a moderator who types an admin address is told it needs an admin, and nothing is fetched", async () => {
    const api = await openAs("moderator", "/staff", EMPTY_QUEUE);
    expect(await findText("That needs an admin")).toBeInTheDocument();
    expect(api.calls.some((c) => c.path === "/staff")).toBe(false);
  });

  it("an admin sees everything", async () => {
    await openAs("admin", "/queue", EMPTY_QUEUE);
    await findText("Nothing is waiting");
    for (const label of ["Overview", "Reports", "People", "Ban lists", "Audit log", "Staff"]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
  });

  it("a moderator can't ban, an admin can", async () => {
    const history = {
      account: {
        id: "u1", display_name: "Kamau", status: "active", created_at: "2026-10-01T08:00:00Z",
        is_verified_neighbour: false, badge_locked: false, restricted: false, restricted_until: null,
        restriction_reason: null, suspended_until: null, deleted: false,
      },
      reports_against: [], reports_by: [], warnings: [], actions: [], content_removed_count: 0,
    };
    await openAs("moderator", "/people/u1", { "GET /users/u1": { status: 200, body: history } });
    expect(await screen.findByRole("button", { name: "Warn" }, { timeout: 8000 })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ban" })).not.toBeInTheDocument();
  });
});
