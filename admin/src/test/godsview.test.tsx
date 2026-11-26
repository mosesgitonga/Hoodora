// God's view (decision D.8), against a mocked API. jsdom has no layout, so the
// map itself has no size here; what is checked is what it asks for, what it
// counts, and that place names stay text.

import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { label, plain, resolutionFor, type MapCell } from "../pages/GodsView";
import { findText, openAs } from "./harness";

function hexagon(id: string, people: number, lat = -0.42, lng = 36.95): MapCell {
  const d = 0.004;
  return {
    id,
    people,
    active: Math.floor(people / 2),
    recent_posts: 1,
    boundary: [
      [lat + d, lng],
      [lat + d / 2, lng + d],
      [lat - d / 2, lng + d],
      [lat - d, lng],
      [lat - d / 2, lng - d],
      [lat + d / 2, lng - d],
    ],
  };
}

function place(name: string, level = "village") {
  return {
    type: "Feature",
    geometry: { type: "Polygon", coordinates: [[[36.94, -0.43], [36.96, -0.43], [36.96, -0.41], [36.94, -0.41], [36.94, -0.43]]] },
    properties: { name, level, ward: "Ruring'u", sub_county: "Nyeri Central", county: "Nyeri", label_at: [-0.42, 36.95] },
  };
}

const CELLS = { status: 200, body: { resolution: 6, cells: [hexagon("86a", 12), hexagon("86b", 3, -0.5, 37.0)], truncated: false, people: 15 } };
const PLACES = { status: 200, body: { type: "FeatureCollection", features: [place("Gatitu"), place("Nyeri", "town"), place("Ruring'u", "ward")] } };

describe("God's view", () => {
  it("draws people and places, and says it is audited", async () => {
    const api = await openAs("admin", "/map", { "GET /map/cells": CELLS, "GET /map/places": PLACES });

    expect(await findText("Admins only. Opening this map is recorded in the audit log.")).toBeInTheDocument();
    expect(await findText(/3 named places./)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("People living here").parentElement?.textContent).toContain("15"));

    const asked = api.calls.filter((c) => c.path === "/map/cells");
    // Once everywhere, to find where people are; then for the view.
    expect(asked[0].url.searchParams.get("resolution")).toBe("6");
    expect(asked[0].url.searchParams.has("west")).toBe(false);
    expect(asked.some((c) => c.url.searchParams.has("west"))).toBe(true);
    expect(api.calls.some((c) => c.path === "/map/places")).toBe(true);
  });

  it("keeps a place's name as text, never HTML", async () => {
    const hostile = '<img src="x" onerror="window.hacked=1">';
    await openAs("admin", "/map", {
      "GET /map/cells": CELLS,
      "GET /map/places": { status: 200, body: { type: "FeatureCollection", features: [place(hostile, "ward")] } },
    });
    expect(await findText(/1 named place\./)).toBeInTheDocument();
    expect(document.querySelector('img[src="x"]')).toBeNull();
    expect((window as unknown as { hacked?: number }).hacked).toBeUndefined();

    // What the map draws as names and tooltips, whatever the zoom: text only.
    const tooltip = plain(hostile);
    expect(tooltip.textContent).toBe(hostile);
    expect(tooltip.querySelector("img")).toBeNull();
    const html = label(hostile, "gods-place").options.html as HTMLElement;
    expect(html.textContent).toBe(hostile);
    expect(html.children).toHaveLength(0);
  });

  it("explains a failure", async () => {
    await openAs("admin", "/map", { "GET /map/cells": { status: 500, body: {} }, "GET /map/places": PLACES });
    expect(await findText("Couldn't load the map's numbers")).toBeInTheDocument();
  });

  it("is plain when nobody lives in view", async () => {
    await openAs("admin", "/map", {
      "GET /map/cells": { status: 200, body: { resolution: 6, cells: [], truncated: false, people: 0 } },
      "GET /map/places": PLACES,
    });
    expect(await findText("Nobody lives here yet")).toBeInTheDocument();
  });

  it("uses larger hexagons further out", () => {
    expect([5, 9, 10, 11, 12, 13, 17].map(resolutionFor)).toEqual([6, 6, 6, 7, 7, 8, 8]);
  });

  it("is for admins only", async () => {
    const api = await openAs("moderator", "/map", { "GET /queue": { status: 200, body: { items: [], next_cursor: null } } });
    expect(await findText("That needs an admin")).toBeInTheDocument();
    expect(screen.queryByText("God's view")).not.toBeInTheDocument();
    expect(api.calls.some((c) => c.path.startsWith("/map"))).toBe(false);
  });
});
