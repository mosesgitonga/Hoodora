// God's view (decisions D.8 and D.9): Kenya, the hexagons with how many people,
// and the named places with their boundaries. People by where they live, where
// they are now, at a past hour, or on a typical day. Admins only; audited.
//
// Drawn with Leaflet from our own data alone: no map tiles, nothing fetched from
// anyone else's servers. Every label is set as text, never as HTML: place names
// come from outside data.

import "leaflet/dist/leaflet.css";
import "./GodsView.css";

import { Alert, Button, Card, DatePicker, Segmented, Slider, Space, Statistic, Typography } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import L from "leaflet";
import { useCallback, useEffect, useRef, useState } from "react";

import { request } from "../api";
import { EmptyState, ErrorState } from "../components";
import kenya from "../kenya.json";
import { THEME } from "../theme";

export interface MapCell {
  id: string;
  people: number;
  /** Where they live only. */
  active?: number;
  recent_posts?: number;
  boundary: [number, number][];
}

interface CellsOut {
  resolution: number;
  cells: MapCell[];
  truncated: boolean;
  people: number;
  hours_recorded?: number;
}

export type Mode = "homes" | "now" | "hour" | "typical";

export interface Showing {
  mode: Mode;
  /** For "hour": the day, in Nairobi. */
  day: Dayjs;
  /** For "hour" and "typical": the hour of the day, Nairobi time. */
  hour: number;
}

const TYPICAL_DAYS = 30;

/** What to ask the API for a view, at a hexagon size. */
export function askFor(showing: Showing, resolution: number): { path: string; query: Record<string, string | number> } {
  switch (showing.mode) {
    case "homes":
      return { path: "/map/cells", query: { resolution } };
    case "now":
      return { path: "/map/presence", query: { mode: "now", resolution } };
    case "hour": {
      const at = `${showing.day.format("YYYY-MM-DD")}T${String(showing.hour).padStart(2, "0")}:00:00+03:00`;
      return { path: "/map/presence", query: { mode: "hour", resolution, at } };
    }
    case "typical":
      return { path: "/map/presence", query: { mode: "typical", resolution, hour_of_day: showing.hour, days: TYPICAL_DAYS } };
  }
}

function count(people: number): string {
  return Number.isInteger(people) ? String(people) : people.toFixed(1);
}

function hourName(hour: number): string {
  return `${String(hour).padStart(2, "0")}:00`;
}

function describe(cell: MapCell, showing: Showing): string {
  const n = count(cell.people);
  switch (showing.mode) {
    case "homes":
      return `${n} ${cell.people === 1 ? "person lives" : "people live"} here · ${cell.active ?? 0} active · ${cell.recent_posts ?? 0} recent posts`;
    case "now":
      return `${n} here in the last 2 hours`;
    case "hour":
      return `${n} here between ${hourName(showing.hour)} and ${hourName((showing.hour + 1) % 24)}`;
    case "typical":
      return `About ${n} here at ${hourName(showing.hour)} on a typical day`;
  }
}

interface PlaceFeature {
  type: "Feature";
  geometry: GeoJSON.Geometry;
  properties: { name: string; level: string; ward: string | null; sub_county: string | null; county: string; label_at: [number, number] };
}

/** The hexagon size for a zoom level: larger hexagons when zoomed out, and each
 * size kept until the next is big enough on screen to carry its number. */
export function resolutionFor(zoom: number): 6 | 7 | 8 {
  if (zoom <= 10) return 6;
  if (zoom <= 12) return 7;
  return 8;
}

/** From which zoom a hexagon is big enough on screen to carry its number: from
 * 9 inward, every zoom shows numbers. */
const COUNT_LABELS_FROM: Record<number, number> = { 6: 9, 7: 11, 8: 13 };
/** A name shows once in this many km: places at different levels often share one. */
const SAME_NAME_KM = 3;
/** From which zoom each kind of place shows its name. */
const NAMES_FROM: Record<string, number> = { ward: 10, town: 10, sublocation: 12, village: 13 };
const SIZE_NAMES: Record<number, string> = { 6: "about 36 km²", 7: "about 5 km²", 8: "about 0.7 km²" };

/** Text for Leaflet, which would read a string as HTML. */
export function plain(text: string): HTMLElement {
  const element = document.createElement("span");
  element.textContent = text;
  return element;
}

export function label(text: string, className: string): L.DivIcon {
  return L.divIcon({ className, html: plain(text), iconSize: [0, 0] });
}

function centre(boundary: [number, number][]): L.LatLng {
  const lat = boundary.reduce((sum, [y]) => sum + y, 0) / boundary.length;
  const lng = boundary.reduce((sum, [, x]) => sum + x, 0) / boundary.length;
  return L.latLng(lat, lng);
}

export function GodsView() {
  const element = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const hexagons = useRef<L.LayerGroup | null>(null);
  const counts = useRef<L.LayerGroup | null>(null);
  const placeNames = useRef<Record<string, L.LayerGroup>>({});
  const asked = useRef(0);
  const [showing, setShowing] = useState<Showing>({ mode: "homes", day: dayjs().subtract(1, "day"), hour: 18 });
  const showingRef = useRef(showing);
  showingRef.current = showing;
  const [view, setView] = useState<{ resolution: number; cells: MapCell[]; truncated: boolean; hoursRecorded?: number } | null>(null);
  const [places, setPlaces] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [extent, setExtent] = useState<L.LatLngBounds | null>(null);

  const showLabels = useCallback(() => {
    const m = map.current;
    if (!m) return;
    const zoom = m.getZoom();
    const resolution = resolutionFor(zoom);
    if (counts.current) {
      if (zoom >= COUNT_LABELS_FROM[resolution]) counts.current.addTo(m);
      else counts.current.remove();
    }
    for (const [level, group] of Object.entries(placeNames.current)) {
      if (zoom >= (NAMES_FROM[level] ?? 13)) group.addTo(m);
      else group.remove();
    }
  }, []);

  const loadCells = useCallback(async () => {
    const m = map.current;
    if (!m) return;
    const resolution = resolutionFor(m.getZoom());
    const bounds = m.getBounds().pad(0.2);
    const ticket = ++asked.current;
    const now = showingRef.current;
    const { path, query } = askFor(now, resolution);
    try {
      const out = await request<CellsOut>("GET", path, {
        query: {
          ...query,
          west: Math.max(-180, bounds.getWest()),
          south: Math.max(-90, bounds.getSouth()),
          east: Math.min(180, bounds.getEast()),
          north: Math.min(90, bounds.getNorth()),
        },
      });
      if (ticket !== asked.current) return; // a newer view asked since
      setError(null);
      setView({ resolution, cells: out.cells, truncated: out.truncated, hoursRecorded: out.hours_recorded });
      const most = Math.max(1, ...out.cells.map((cell) => cell.people));
      hexagons.current?.clearLayers();
      counts.current?.clearLayers();
      for (const cell of out.cells) {
        const strength = cell.people ? Math.log1p(cell.people) / Math.log1p(most) : 0;
        L.polygon(cell.boundary, {
          color: THEME.token.colorPrimary,
          weight: 1,
          fillColor: THEME.token.colorPrimary,
          fillOpacity: 0.08 + 0.4 * strength,
        })
          .bindTooltip(plain(describe(cell, now)), { sticky: true })
          .addTo(hexagons.current!);
        L.marker(centre(cell.boundary), {
          icon: label(count(cell.people), "gods-count"),
          interactive: false,
          keyboard: false,
        }).addTo(counts.current!);
      }
      showLabels();
    } catch (failure) {
      if (ticket === asked.current) setError(failure);
    }
  }, [showLabels]);

  // The map, once.
  useEffect(() => {
    if (!element.current) return;
    const m = L.map(element.current, { minZoom: 5, maxZoom: 17, zoomSnap: 1 });
    map.current = m;
    m.attributionControl.setPrefix(false);
    m.attributionControl.addAttribution("Kenya: Natural Earth");
    const country = L.geoJSON(kenya as GeoJSON.Feature, {
      style: { color: "#9C8F86", weight: 1.5, fillColor: "#FBF7F3", fillOpacity: 1 },
      interactive: false,
    }).addTo(m);
    m.fitBounds(country.getBounds());
    hexagons.current = L.layerGroup().addTo(m);
    counts.current = L.layerGroup();
    m.on("moveend", () => void loadCells());
    m.on("zoomend", showLabels);
    return () => {
      m.remove();
      map.current = null;
    };
  }, [loadCells, showLabels]);

  // A different view: the same map, new numbers. Not on the first render: the
  // first load waits until the map has found where people are.
  const firstShowing = useRef(true);
  useEffect(() => {
    if (firstShowing.current) {
      firstShowing.current = false;
      return;
    }
    if (map.current) void loadCells();
  }, [showing, loadCells]);

  // Places and where people are, once; then the hexagons for the view.
  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const [collection, everywhere] = await Promise.all([
          request<{ features: PlaceFeature[] }>("GET", "/map/places"),
          request<CellsOut>("GET", "/map/cells", { query: { resolution: 6 } }),
        ]);
        if (!live || !map.current) return;
        const m = map.current;
        const outlines = L.layerGroup();
        const groups: Record<string, L.LayerGroup> = {};
        // The API sends wards, then towns, sublocations and villages: the first
        // place to claim a name nearby keeps it.
        const named: { name: string; at: L.LatLng }[] = [];
        for (const place of collection.features) {
          const { name, level, ward, county, label_at } = place.properties;
          L.geoJSON(place as GeoJSON.Feature, {
            style: { color: "#4A3F38", weight: level === "ward" ? 1.5 : 0.8, fill: false, dashArray: level === "village" ? "2 3" : undefined },
          })
            .bindTooltip(plain(`${name} (${level})${ward && ward !== name ? ` · ${ward}` : ""} · ${county}`), { sticky: true })
            .addTo(outlines);
          const at = L.latLng(label_at);
          const key = name.trim().toLowerCase();
          if (named.some((other) => other.name === key && other.at.distanceTo(at) < SAME_NAME_KM * 1000)) continue;
          named.push({ name: key, at });
          groups[level] ??= L.layerGroup();
          L.marker(at, { icon: label(name, `gods-place gods-place-${level}`), interactive: false, keyboard: false }).addTo(groups[level]);
        }
        outlines.addTo(m);
        placeNames.current = groups;
        setPlaces(collection.features.length);
        if (everywhere.cells.length) {
          const bounds = L.latLngBounds(everywhere.cells.flatMap((cell) => cell.boundary));
          setExtent(bounds);
          m.fitBounds(bounds.pad(0.3), { maxZoom: 12 });
        }
        showLabels();
        await loadCells();
      } catch (failure) {
        if (live) setError(failure);
      }
    })();
    return () => {
      live = false;
    };
  }, [loadCells, showLabels]);

  const people = Math.round((view?.cells.reduce((sum, cell) => sum + cell.people, 0) ?? 0) * 10) / 10;
  const active = view?.cells.reduce((sum, cell) => sum + (cell.active ?? 0), 0) ?? 0;
  const heading = {
    homes: "People living here",
    now: "Here in the last 2 hours",
    hour: `Here ${hourName(showing.hour)}–${hourName((showing.hour + 1) % 24)}, ${showing.day.format("D MMM")}`,
    typical: `Here at ${hourName(showing.hour)}, on average`,
  }[showing.mode];
  const withPeople = view?.cells.filter((cell) => cell.people > 0).length ?? 0;

  return (
    <div className="gods-layout">
      <Card styles={{ body: { padding: 0 } }}>
        <div ref={element} style={{ height: "calc(100vh - 160px)", minHeight: 480, background: "#EAF0F2", borderRadius: 8 }} aria-label="Map of Kenya" />
      </Card>
      <div style={{ display: "grid", gap: 16 }}>
        <Card title="God's view" size="small">
          <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
            Hexagons with how many people, and the named places people see as "near …".
          </Typography.Paragraph>
          <Segmented<Mode>
            block
            value={showing.mode}
            onChange={(mode) => setShowing((was) => ({ ...was, mode }))}
            options={[
              { value: "homes", label: "Homes" },
              { value: "now", label: "Now" },
              { value: "hour", label: "An hour" },
              { value: "typical", label: "Typical day" },
            ]}
            aria-label="Show people by"
          />
          {showing.mode === "hour" ? (
            <div style={{ marginTop: 12 }}>
              <DatePicker
                value={showing.day}
                allowClear={false}
                disabledDate={(day) => day.isAfter(dayjs(), "day")}
                onChange={(day) => day && setShowing((was) => ({ ...was, day }))}
                aria-label="Day"
              />
            </div>
          ) : null}
          {showing.mode === "hour" || showing.mode === "typical" ? (
            <div style={{ marginTop: 8 }}>
              <Typography.Text>{hourName(showing.hour)} Nairobi time</Typography.Text>
              <Slider
                min={0}
                max={23}
                value={showing.hour}
                onChange={(hour) => setShowing((was) => ({ ...was, hour }))}
                tooltip={{ formatter: (hour) => hourName(hour ?? 0) }}
                aria-label="Hour"
              />
            </div>
          ) : null}
          <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 8 }}>
            {
              {
                homes: "Where people live.",
                now: "App users in the last 2 hours, where their phone last was (or at home).",
                hour: "App users in that hour, where their phone last was. Kept hour by hour for a year.",
                typical: `The average at that hour over the last ${TYPICAL_DAYS} days.`,
              }[showing.mode]
            }{" "}
            Counts only, never who.
          </Typography.Paragraph>
          <Alert type="info" showIcon message="Admins only. Opening this map is recorded in the audit log." />
        </Card>
        {error ? (
          <Card size="small">
            <ErrorState error={error} onRetry={() => void loadCells()} title="Couldn't load the map's numbers" />
          </Card>
        ) : (
          <Card title="In view" size="small">
            <Statistic title={heading} value={people} />
            <Space size="large" style={{ marginTop: 8 }}>
              {showing.mode === "homes" ? <Statistic title="Active" value={active} valueStyle={{ fontSize: 18 }} /> : null}
              <Statistic title="Hexagons" value={withPeople} valueStyle={{ fontSize: 18 }} />
            </Space>
            {showing.mode === "typical" && view ? (
              <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
                {view.hoursRecorded ? `Averaged over ${view.hoursRecorded} recorded ${view.hoursRecorded === 1 ? "hour" : "hours"}.` : "Nothing recorded at this hour yet: counting started with this release."}
              </Typography.Paragraph>
            ) : null}
            <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
              {view ? `Hexagons of ${SIZE_NAMES[view.resolution]}. Zoom in for smaller ones and their numbers.` : "Loading…"}
            </Typography.Paragraph>
            {view?.truncated ? <Alert type="warning" showIcon message="Too many hexagons to show here: zoom in." style={{ marginTop: 8 }} /> : null}
            {view && withPeople === 0 ? (
              <EmptyState title={showing.mode === "homes" ? "Nobody lives here yet" : "Nobody here then"}>
                Pan or zoom out{showing.mode === "homes" ? "" : ", or pick another time"}.
              </EmptyState>
            ) : null}
          </Card>
        )}
        <Card size="small" title="Go to">
          <Space wrap>
            <Button onClick={() => map.current?.fitBounds(L.geoJSON(kenya as GeoJSON.Feature).getBounds())}>All of Kenya</Button>
            <Button disabled={!extent} onClick={() => extent && map.current?.fitBounds(extent.pad(0.3), { maxZoom: 13 })}>
              Where people are
            </Button>
          </Space>
          <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
            {places === null ? "Loading places…" : `${places} named ${places === 1 ? "place" : "places"}.`} Names show as you zoom in: wards and towns first,
            villages last. Hover a hexagon or a place for details.
          </Typography.Paragraph>
        </Card>
      </div>
    </div>
  );
}
