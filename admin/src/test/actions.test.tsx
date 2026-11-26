// Actions: nothing is sent until the dialog's own button is pressed, and then
// exactly what the API takes.

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import dayjs from "dayjs";
import { describe, expect, it } from "vitest";

import { day, waited, when } from "../format";
import { nairobiStart } from "../pages/Audit";
import { daysUntil } from "../pages/Person";
import { banEntry, contentDetail, history, staffList } from "./fixtures";
import { findText, openAs, staff } from "./harness";

const posts = (api: { calls: { method: string; path: string }[] }, path: string) =>
  api.calls.filter((c) => c.method !== "GET" && c.path === path);

async function dialog(title: string) {
  return within(await screen.findByRole("dialog", { name: title }, { timeout: 8000 }));
}

describe("taking content down", () => {
  it("asks first, needs a reason, and sends nothing on cancel", async () => {
    const api = await openAs("moderator", "/queue/post/p1", {
      "GET /content/post/p1": { status: 200, body: contentDetail() },
      "POST /content/post/p1/remove": { status: 200, body: { reports_resolved: 1 } },
      "GET /queue": { status: 200, body: { items: [], next_cursor: null } },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Remove" }, { timeout: 8000 }));
    let box = await dialog("Remove this?");
    expect(box.getByText(/disappears for everyone/)).toBeInTheDocument();
    expect(posts(api, "/content/post/p1/remove")).toHaveLength(0);

    await userEvent.click(box.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(posts(api, "/content/post/p1/remove")).toHaveLength(0);

    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    box = await dialog("Remove this?");
    await userEvent.click(box.getByRole("button", { name: "Remove it" }));
    expect(await box.findByText("Reason, shown to the author is needed.")).toBeInTheDocument();
    expect(posts(api, "/content/post/p1/remove")).toHaveLength(0);

    await userEvent.type(box.getByLabelText("Reason, shown to the author"), "Advance-fee scam");
    await userEvent.click(box.getByRole("button", { name: "Remove it" }));
    await waitFor(() => expect(posts(api, "/content/post/p1/remove")).toHaveLength(1));
    expect(api.calls.find((c) => c.path === "/content/post/p1/remove")?.body).toEqual({ reason: "Advance-fee scam" });
    expect(await findText("Removed.")).toBeInTheDocument();
  });

  it("upholds and dismisses with the right outcome, and shows a refusal in the dialog", async () => {
    const api = await openAs("moderator", "/queue/post/p1", {
      "GET /content/post/p1": { status: 200, body: contentDetail() },
      "POST /content/post/p1/resolve": (body) =>
        (body as { outcome: string }).outcome === "upheld"
          ? { status: 409, body: { error: { code: "conflict", message: "Those reports are already closed" } } }
          : { status: 200, body: { reports_resolved: 1 } },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Uphold reports" }, { timeout: 8000 }));
    let box = await dialog("Uphold the reports?");
    await userEvent.click(box.getByRole("button", { name: "Uphold" }));
    expect(await box.findByText("Those reports are already closed")).toBeInTheDocument();
    await userEvent.click(box.getByRole("button", { name: "Cancel" }));

    await userEvent.click(screen.getByRole("button", { name: "Dismiss reports" }));
    box = await dialog("Dismiss the reports?");
    await userEvent.click(box.getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(posts(api, "/content/post/p1/resolve")).toHaveLength(2));
    expect(api.calls.filter((c) => c.path === "/content/post/p1/resolve").map((c) => (c.body as { outcome: string }).outcome)).toEqual(["upheld", "dismissed"]);
  });
});

describe("acting on a person", () => {
  it("suspends until a date, sending the days the API takes", async () => {
    const api = await openAs("moderator", "/people/u1", {
      "GET /users/u1": { status: 200, body: history() },
      "POST /users/u1/suspend": { status: 200, body: history().account },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Suspend" }, { timeout: 8000 }));
    const box = await dialog("Suspend Kamau Njoroge?");
    await userEvent.type(box.getByLabelText("Reason, shown to them"), "Repeated harassment");
    const until = dayjs().add(10, "day").format("YYYY-MM-DD");
    await userEvent.type(box.getByLabelText("Until"), `${until}{enter}`);
    await userEvent.click(box.getByRole("button", { name: "Suspend" }));
    await waitFor(() => expect(posts(api, "/users/u1/suspend")).toHaveLength(1));
    const body = api.calls.find((c) => c.path === "/users/u1/suspend")?.body as { reason: string; days: number };
    expect(body.reason).toBe("Repeated harassment");
    expect([9, 10]).toContain(body.days);
  });

  it("an admin's ban asks first and sends every choice", async () => {
    const api = await openAs("admin", "/people/u1", {
      "GET /users/u1": { status: 200, body: history() },
      "POST /users/u1/ban": { status: 200, body: history({ status: "banned" }).account },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Ban" }, { timeout: 8000 }));
    const box = await dialog("Ban Kamau Njoroge?");
    expect(posts(api, "/users/u1/ban")).toHaveLength(0);
    await userEvent.type(box.getByLabelText("Reason"), "Scam ring");
    await userEvent.click(box.getByLabelText("Also take down everything they have posted"));
    await userEvent.click(box.getByRole("button", { name: "Ban" }));
    await waitFor(() => expect(posts(api, "/users/u1/ban")).toHaveLength(1));
    expect(api.calls.find((c) => c.path === "/users/u1/ban")?.body).toEqual({
      reason: "Scam ring",
      ban_phone: true,
      ban_devices: true,
      ban_google_account: true,
      remove_content: true,
    });
  });
});

describe("ban lists and staff", () => {
  it("lifting a ban asks first", async () => {
    const api = await openAs("admin", "/bans", {
      "GET /bans/phones": { status: 200, body: { items: [banEntry()], next_cursor: null } },
      [`DELETE /bans/phones/${banEntry().id}`]: { status: 204 },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Lift" }, { timeout: 8000 }));
    const box = await dialog("Lift this ban?");
    expect(api.calls.some((c) => c.method === "DELETE")).toBe(false);
    await userEvent.click(box.getByRole("button", { name: "Lift it" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "DELETE")).toBe(true));
  });

  it("deactivating a moderator asks first", async () => {
    const api = await openAs("admin", "/staff", {
      "GET /staff": { status: 200, body: staffList() },
      "PATCH /staff/s-mod": { status: 200, body: staff("moderator", { disabled: true }) },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Deactivate" }, { timeout: 8000 }));
    const box = await dialog("Deactivate Otieno Moderator?");
    expect(api.calls.some((c) => c.method === "PATCH")).toBe(false);
    await userEvent.click(box.getByRole("button", { name: "Deactivate" }));
    await waitFor(() => expect(api.calls.find((c) => c.method === "PATCH")?.body).toEqual({ disabled: true }));
  });

  it("a new moderator's sign-in details are shown once, as text", async () => {
    await openAs("admin", "/staff", {
      "GET /staff": { status: 200, body: staffList() },
      "POST /staff": {
        status: 201,
        body: { staff: staff("moderator", { id: "s-new", display_name: "Akinyi" }), temporary_password: "tmp-pass-123", totp_secret: "JBSWY3DPEHPK3PXP", totp_uri: "otpauth://totp/Hoodora:akinyi?secret=JBSWY3DPEHPK3PXP" },
      },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Add a moderator" }, { timeout: 8000 }));
    const box = await dialog("Add a staff account");
    await userEvent.type(box.getByLabelText("Email"), "akinyi@hoodora.test");
    await userEvent.type(box.getByLabelText("Name"), "Akinyi");
    await userEvent.click(box.getByRole("button", { name: "Create account" }));
    const shown = await dialog("Sign-in details for Akinyi");
    expect(shown.getByText("JBSWY3DPEHPK3PXP")).toBeInTheDocument();
    expect(shown.getByText("tmp-pass-123")).toBeInTheDocument();
    expect(shown.getByText(/Shown once/)).toBeInTheDocument();
    await userEvent.click(shown.getByRole("button", { name: "I've passed these on" }));
    await waitFor(() => expect(screen.queryByText("JBSWY3DPEHPK3PXP")).not.toBeInTheDocument());
  });
});

describe("dates", () => {
  it("are Nairobi's", () => {
    // 21:30 UTC is 00:30 the next day in Nairobi.
    expect(when("2026-11-25T21:30:00Z")).toBe("26 Nov 2026, 00:30");
    expect(day("2026-11-26")).toBe("26 Nov");
    expect(nairobiStart(dayjs("2026-11-26"))).toBe("2026-11-26T00:00:00+03:00");
    expect(nairobiStart(dayjs("2026-11-26"), 1)).toBe("2026-11-27T00:00:00+03:00");
  });

  it("turn an end date into whole days, within what the API allows", () => {
    const now = new Date("2026-11-26T10:00:00Z");
    expect(daysUntil(new Date("2026-11-27T10:00:00Z"), now)).toBe(1);
    expect(daysUntil(new Date("2026-12-06T09:00:00Z"), now)).toBe(10);
    expect(daysUntil(new Date("2026-11-26T11:00:00Z"), now)).toBe(1);
    expect(daysUntil(new Date("2028-01-01T00:00:00Z"), now)).toBe(365);
    expect(waited("2026-11-26T07:00:00Z", now)).toBe("3 h");
    expect(waited("2026-11-22T10:00:00Z", now)).toBe("4 days");
  });
});

describe("the CSP nonce", () => {
  it("is on every style element the page creates", async () => {
    const { tagCreatedStyles } = await import("../csp");
    const doc = document.implementation.createHTMLDocument("x");
    tagCreatedStyles("abc123", doc);
    expect((doc.createElement("style") as HTMLStyleElement).nonce).toBe("abc123");
    expect((doc.createElement("STYLE") as HTMLStyleElement).nonce).toBe("abc123");
    expect(doc.createElement("div").getAttribute("nonce")).toBeNull();
    // No nonce on the page (development): nothing is changed.
    const plain = document.implementation.createHTMLDocument("y");
    const before = plain.createElement;
    tagCreatedStyles(undefined, plain);
    expect(plain.createElement).toBe(before);
  });
});
