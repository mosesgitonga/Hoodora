// Every screen against a mocked API: loaded, empty and error.

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { auditEvent, banEntry, contentDetail, history, queueItem, stats, account, staffList } from "./fixtures";
import { apiError, findText, openAs } from "./harness";

const page = <T,>(items: T[], next: string | null = null) => ({ status: 200, body: { items, next_cursor: next } });
const SERVER_DOWN = apiError(500, "The server had a problem.");

describe("Overview", () => {
  it("shows today, the month, the queue and the radius", async () => {
    await openAs("admin", "/overview", { "GET /stats": { status: 200, body: stats() } });
    expect(await findText("Sign-ups today")).toBeInTheDocument();
    expect(screen.getByText("Active people")).toBeInTheDocument();
    expect(screen.getByText("Needed more people")).toBeInTheDocument();
    expect(screen.getByText("The last 30 days")).toBeInTheDocument();
    expect(screen.getByText(/5 things in the queue/)).toBeInTheDocument();
    expect(screen.getByText(/nobody is named here/)).toBeInTheDocument();
  });

  it("says so when nobody is active and nothing waits", async () => {
    const quiet = stats();
    quiet.totals.waiting = 0;
    quiet.radius = { people: 0, bands: [], by_condition: {} };
    await openAs("admin", "/overview", { "GET /stats": { status: 200, body: quiet } });
    expect(await findText("No active people yet")).toBeInTheDocument();
    expect(screen.getByText("The queue is empty.")).toBeInTheDocument();
  });

  it("explains a failure and offers to try again", async () => {
    await openAs("admin", "/overview", { "GET /stats": SERVER_DOWN });
    expect(await findText("Couldn't load the overview")).toBeInTheDocument();
    expect(screen.getByText("The server had a problem.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

describe("Reports queue", () => {
  it("lists one row per thing and opens it", async () => {
    const api = await openAs("moderator", "/queue", {
      "GET /queue": page([queueItem(), queueItem({ target_id: "p2", held: true, reasons: [], excerpt: "Held one", report_count: 0, trusted_report_count: 0 })]),
      "GET /content/post/p1": { status: 200, body: contentDetail() },
    });
    expect(await findText("Cheap phones, send M-Pesa first")).toBeInTheDocument();
    expect(screen.getByText("Spam")).toBeInTheDocument();
    expect(screen.getByText("Held")).toBeInTheDocument();
    expect(screen.getByText("2 (1 trusted)")).toBeInTheDocument();

    await userEvent.click(screen.getByText("Cheap phones, send M-Pesa first"));
    expect(await findText("Same post in every group")).toBeInTheDocument();
    expect(api.calls.some((c) => c.path === "/content/post/p1")).toBe(true);
  });

  it("loads the next page by cursor", async () => {
    const api = await openAs("moderator", "/queue", {
      "GET /queue": (_, url) =>
        url.searchParams.get("cursor") === "c2" ? page([queueItem({ target_id: "p9", excerpt: "Second page" })]) : page([queueItem()], "c2"),
    });
    await userEvent.click(await screen.findByRole("button", { name: "Load more" }, { timeout: 8000 }));
    expect(await findText("Second page")).toBeInTheDocument();
    expect(api.calls.filter((c) => c.path === "/queue").map((c) => c.url.searchParams.get("cursor"))).toEqual([null, "c2"]);
  });

  it("is empty when nothing waits, and explains a failure", async () => {
    await openAs("moderator", "/queue", { "GET /queue": page([]) });
    expect(await findText("Nothing is waiting")).toBeInTheDocument();
  });

  it("explains a failure", async () => {
    await openAs("moderator", "/queue", { "GET /queue": SERVER_DOWN });
    expect(await findText("Couldn't load the queue")).toBeInTheDocument();
  });
});

describe("A thing in the queue", () => {
  it("shows the content, its author and its reports", async () => {
    await openAs("moderator", "/queue/post/p1", { "GET /content/post/p1": { status: 200, body: contentDetail() } });
    expect(await findText("Cheap phones, send M-Pesa first")).toBeInTheDocument();
    expect(screen.getByText("Kamau Njoroge")).toHaveAttribute("href", "/people/u1");
    expect(screen.getByText("Reports (1)")).toBeInTheDocument();
  });

  it("is plain about a held thing with no reports", async () => {
    await openAs("moderator", "/queue/post/p1", {
      "GET /content/post/p1": { status: 200, body: contentDetail({ status: "hidden_pending_review" }, false) },
    });
    expect(await findText("No reports")).toBeInTheDocument();
    expect(screen.getByText("Held for review")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Restore" })).toBeInTheDocument();
  });

  it("explains a missing thing", async () => {
    await openAs("moderator", "/queue/post/p1", { "GET /content/post/p1": apiError(404, "That content doesn't exist") });
    expect(await findText("That content doesn't exist")).toBeInTheDocument();
  });
});

describe("People", () => {
  it("finds someone by number, without showing the number back", async () => {
    const api = await openAs("moderator", "/people", { "POST /users/lookup": { status: 200, body: [account()] } });
    await userEvent.type(await screen.findByPlaceholderText("0712 345 678", {}, { timeout: 8000 }), "0712345678");
    await userEvent.click(screen.getByRole("button", { name: "Look up" }));
    expect(await findText("Kamau Njoroge")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open" })).toHaveAttribute("href", "/people/u1");
    const call = api.calls.find((c) => c.path === "/users/lookup");
    expect(call?.body).toEqual({ phone_number: "0712345678" });
    // In the body, never the address.
    expect(call?.url.search).toBe("");
  });

  it("says when nobody has the number, and explains a refusal", async () => {
    await openAs("moderator", "/people", {
      "POST /users/lookup": (body) =>
        (body as { phone_number: string }).phone_number === "nonsense"
          ? apiError(400, "That doesn't look like a phone number")
          : { status: 200, body: [] },
    });
    const input = await screen.findByPlaceholderText("0712 345 678", {}, { timeout: 8000 });
    await userEvent.type(input, "0799000111");
    await userEvent.click(screen.getByRole("button", { name: "Look up" }));
    expect(await findText("Nobody has that number.")).toBeInTheDocument();
    await userEvent.clear(input);
    await userEvent.type(input, "nonsense");
    await userEvent.click(screen.getByRole("button", { name: "Look up" }));
    expect(await findText("That doesn't look like a phone number")).toBeInTheDocument();
  });

  it("shows a person's standing and history", async () => {
    await openAs("moderator", "/people/u1", { "GET /users/u1": { status: 200, body: history({ restricted: true, restricted_until: "2026-12-01T00:00:00Z", restriction_reason: "Spam" }) } });
    expect(await findText("Kamau Njoroge")).toBeInTheDocument();
    expect(screen.getByText("Restricted")).toBeInTheDocument();
    expect(screen.getByText("Reports against (1)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Lift restriction" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Restrict" })).not.toBeInTheDocument();
  });

  it("is plain about a clean record", async () => {
    await openAs("moderator", "/people/u1", { "GET /users/u1": { status: 200, body: history({}, true) } });
    expect(await findText("Nobody has reported them")).toBeInTheDocument();
  });

  it("explains a failure", async () => {
    await openAs("moderator", "/people/u1", { "GET /users/u1": apiError(404, "No such account") });
    expect(await findText("Couldn't load this person")).toBeInTheDocument();
  });
});

describe("Ban lists", () => {
  it("lists hashed entries without any number, and says why", async () => {
    await openAs("admin", "/bans", { "GET /bans/phones": page([banEntry()]), "GET /bans/devices": page([]) });
    expect(await findText("Scam calls")).toBeInTheDocument();
    expect(screen.getByText(/can't be shown/)).toBeInTheDocument();
    expect(screen.queryByText(/\+254|07\d{8}/)).not.toBeInTheDocument();
  });

  it("is empty, and explains a failure", async () => {
    await openAs("admin", "/bans", { "GET /bans/phones": page([]) });
    expect(await findText("No numbers are banned")).toBeInTheDocument();
  });

  it("explains a failure", async () => {
    await openAs("admin", "/bans", { "GET /bans/phones": SERVER_DOWN });
    expect(await findText("Couldn't load the list")).toBeInTheDocument();
  });
});

describe("Audit log", () => {
  it("lists events, names staff, and filters by action", async () => {
    const api = await openAs("admin", "/audit", {
      "GET /staff": { status: 200, body: staffList() },
      "GET /audit": (_, url) =>
        url.searchParams.get("action") === "user_warned" ? page([]) : page([auditEvent()]),
    });
    expect(await findText("Content removed")).toBeInTheDocument();
    expect(await findText("Otieno Moderator")).toBeInTheDocument();

    const action = screen.getByRole("combobox", { name: "Action" });
    await userEvent.click(action);
    await userEvent.type(action, "User warned");
    await userEvent.click(await within(document.body).findByTitle("User warned"));
    expect(await findText("Nothing matches")).toBeInTheDocument();
    expect(api.calls.some((c) => c.path === "/audit" && c.url.searchParams.get("action") === "user_warned")).toBe(true);
  });

  it("explains a failure", async () => {
    await openAs("admin", "/audit", { "GET /staff": { status: 200, body: [] }, "GET /audit": SERVER_DOWN });
    expect(await findText("Couldn't load the audit log")).toBeInTheDocument();
  });
});

describe("Staff", () => {
  it("lists accounts and marks the signed-in one", async () => {
    await openAs("admin", "/staff", { "GET /staff": { status: 200, body: staffList() } });
    expect(await findText("Otieno Moderator")).toBeInTheDocument();
    expect(screen.getByText("You")).toBeInTheDocument();
  });

  it("is plain about an empty list", async () => {
    await openAs("admin", "/staff", { "GET /staff": { status: 200, body: [] } });
    expect(await findText("No staff accounts")).toBeInTheDocument();
  });

  it("explains a failure", async () => {
    await openAs("admin", "/staff", { "GET /staff": SERVER_DOWN });
    expect(await findText("Couldn't load staff")).toBeInTheDocument();
  });
});

describe("My account", () => {
  it("changes the password with a fresh code", async () => {
    const api = await openAs("moderator", "/account", { "POST /me/password": { status: 204 } });
    await userEvent.type(await screen.findByLabelText("Current password", {}, { timeout: 8000 }), "old password here");
    await userEvent.type(screen.getByLabelText("New password"), "a much longer password");
    await userEvent.type(await screen.findByLabelText("Authenticator code"), "654321");
    await userEvent.click(screen.getByRole("button", { name: "Change password" }));
    expect(await findText("Password changed.")).toBeInTheDocument();
    expect(api.calls.find((c) => c.path === "/me/password")?.body).toEqual({
      current_password: "old password here",
      new_password: "a much longer password",
      code: "654321",
    });
  });
});
