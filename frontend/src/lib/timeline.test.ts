import { describe, expect, it } from "vitest";
import type { CatalogIndex, CatalogStatus } from "./catalog";
import {
  SEASON_START,
  buildTimeline,
  durationMs,
  keyTarget,
  monthStarts,
  spreadLabels,
  stripSegments,
  todayInMadrid,
  trackGeometry,
  type TimelineModel,
} from "./timeline";

function index(entries: Array<[string, string, CatalogStatus]>): CatalogIndex {
  const layers: CatalogIndex["layers"] = {};
  for (const [layer, date, status] of entries) {
    const slot = (layers[layer] ??= { dates: [], entries: [] });
    slot.dates.push(date);
    slot.entries.push({
      layer,
      date,
      status,
      cog: `layers/${layer}/${date}.tif`,
      pmtiles: `tiles/${layer}/${date}.pmtiles`,
      bounds: [-3.6, 36.9, -2.6, 37.3],
      resolution_m: 20,
      bands: ["class"],
      units: ["1"],
      source_ids: ["test"],
    });
  }
  return { schema_version: 1, generated_at: "2026-11-22T00:00:00+00:00", layers };
}

function model(entries: Array<[string, string, CatalogStatus]>, today = "2026-11-22"): TimelineModel {
  const built = buildTimeline(index(entries), today);
  if (!built) throw new Error("expected a timeline");
  return built;
}

const at = (m: TimelineModel, date: string) => m.days.findIndex((day) => day.date === date);

describe("buildTimeline", () => {
  it("has no timeline when the catalogue lists nothing", () => {
    expect(buildTimeline(index([]), "2026-11-22")).toBeNull();
    expect(buildTimeline({ ...index([]), layers: { rgb: { dates: [], entries: [] } } }, "2026-11-22")).toBeNull();
  });

  it("spans every day from the season start to today, even with one product", () => {
    const m = model([["snow_obs", "2026-11-10", "observed"]]);
    expect(m.days[0].date).toBe(SEASON_START);
    expect(m.days[m.days.length - 1].date).toBe("2026-11-22");
    // 2025-10-01 .. 2026-11-22 inclusive.
    expect(m.days).toHaveLength(418);
    expect(m.days[m.todayIndex].date).toBe("2026-11-22");
    expect(new Set(m.days.map((day) => day.date)).size).toBe(418);
  });

  it("crosses the end of February and the year without gaps", () => {
    const m = model([["snow_obs", "2026-03-01", "observed"]]);
    expect(m.days[at(m, "2026-02-28") + 1].date).toBe("2026-03-01");
    expect(m.days[at(m, "2025-12-31") + 1].date).toBe("2026-01-01");
  });

  it("starts earlier when the catalogue does and extends to the last forecast day", () => {
    const m = model([
      ["snow_depth", "2025-09-28", "modelled"],
      ["snow_depth", "2026-11-25", "forecast"],
    ]);
    expect(m.days[0].date).toBe("2025-09-28");
    expect(m.days[m.days.length - 1].date).toBe("2026-11-25");
    expect(m.days[m.todayIndex].date).toBe("2026-11-22");
  });

  it("keeps every status of a day, best first, and marks empty days pending", () => {
    const m = model([
      ["snow_depth", "2026-02-21", "modelled"],
      ["snow_gapfill", "2026-02-21", "gapfilled"],
      ["snow_obs", "2026-02-21", "observed"],
      ["snow_depth", "2026-02-22", "modelled"],
    ]);
    expect(m.days[at(m, "2026-02-21")].statuses).toEqual(["observado", "rellenado", "modelado"]);
    expect(m.days[at(m, "2026-02-21")].best).toBe("observado");
    expect(m.days[at(m, "2026-02-22")].best).toBe("modelado");
    expect(m.days[at(m, "2026-02-23")]).toMatchObject({ statuses: [], best: "pendiente" });
    expect(m.dataIndices).toEqual([at(m, "2026-02-21"), at(m, "2026-02-22")]);
    expect(m.observedIndices).toEqual([at(m, "2026-02-21")]);
  });

  it("opens on the latest product up to today, not on a forecast", () => {
    const m = model([
      ["snow_obs", "2026-11-20", "observed"],
      ["snow_depth", "2026-11-24", "forecast"],
    ]);
    expect(m.days[m.latestIndex].date).toBe("2026-11-20");
  });

  it("falls back to the latest forecast when nothing else exists", () => {
    const m = model([["snow_depth", "2026-11-24", "forecast"]]);
    expect(m.days[m.latestIndex].date).toBe("2026-11-24");
  });
});

describe("locked layers on the timeline", () => {
  it("does not count v1 SWE entries as products of a day", () => {
    const m = model([
      ["swe", "2026-02-21", "modelled"],
      ["snow_obs", "2026-02-22", "observed"],
    ]);
    expect(m.days[at(m, "2026-02-21")].statuses).toEqual([]);
    expect(m.dataIndices).toEqual([at(m, "2026-02-22")]);
  });
});

describe("stripSegments", () => {
  it("merges runs of one status and splits the forecast slot at today", () => {
    const m = model(
      [
        ["snow_depth", "2026-11-18", "modelled"],
        ["snow_depth", "2026-11-19", "modelled"],
        ["snow_depth", "2026-11-23", "forecast"],
      ],
      "2026-11-21",
    );
    const segments = stripSegments(m);
    const start = at(m, "2026-11-18");
    expect(segments).toEqual([
      { start: 0, end: start, status: "pendiente", forecastSlot: false },
      { start, end: start + 2, status: "modelado", forecastSlot: false },
      { start: start + 2, end: m.todayIndex + 1, status: "pendiente", forecastSlot: false },
      { start: m.todayIndex + 1, end: m.todayIndex + 2, status: "pendiente", forecastSlot: true },
      { start: m.todayIndex + 2, end: m.todayIndex + 3, status: "prevision", forecastSlot: true },
    ]);
    // Every day belongs to exactly one segment.
    expect(segments.reduce((sum, s) => sum + s.end - s.start, 0)).toBe(m.days.length);
  });
});

describe("keyTarget", () => {
  const m = model([
    ["snow_obs", "2026-01-10", "observed"],
    ["snow_depth", "2026-01-12", "modelled"],
    ["snow_obs", "2026-01-20", "observed"],
  ]);
  const jan15 = at(m, "2026-01-15");

  it("steps one day with the arrows", () => {
    expect(keyTarget(m, jan15, "ArrowLeft", false)).toBe(jan15 - 1);
    expect(keyTarget(m, jan15, "ArrowRight", false)).toBe(jan15 + 1);
  });

  it("jumps to the previous or next clear pass with Shift, skipping modelled days", () => {
    expect(keyTarget(m, jan15, "ArrowLeft", true)).toBe(at(m, "2026-01-10"));
    expect(keyTarget(m, jan15, "ArrowRight", true)).toBe(at(m, "2026-01-20"));
    expect(keyTarget(m, at(m, "2026-01-20"), "ArrowRight", true)).toBeNull();
  });

  it("goes to the ends with Home and End and stops there", () => {
    expect(keyTarget(m, jan15, "Home", false)).toBe(0);
    expect(keyTarget(m, jan15, "End", false)).toBe(m.days.length - 1);
    expect(keyTarget(m, 0, "ArrowLeft", false)).toBeNull();
    expect(keyTarget(m, m.days.length - 1, "ArrowRight", false)).toBeNull();
    expect(keyTarget(m, 0, "Home", false)).toBeNull();
  });

  it("ignores other keys", () => {
    expect(keyTarget(m, jan15, "a", false)).toBeNull();
    expect(keyTarget(m, jan15, "Enter", false)).toBeNull();
  });

  it("reaches every day of the history one arrow press at a time", () => {
    const seen = [0];
    let current: number | null = 0;
    while ((current = keyTarget(m, current, "ArrowRight", false)) !== null) seen.push(current);
    expect(seen).toEqual(m.days.map((_, i) => i));
  });
});

describe("monthStarts and today", () => {
  it("labels the first of every month on the track", () => {
    const m = model([["snow_obs", "2026-01-10", "observed"]], "2026-03-05");
    expect(monthStarts(m).map((month) => month.date)).toEqual([
      "2025-10-01",
      "2025-11-01",
      "2025-12-01",
      "2026-01-01",
      "2026-02-01",
      "2026-03-01",
    ]);
  });

  it("takes today in Europe/Madrid, not UTC", () => {
    // 23:30 UTC on 21 Nov is already 22 Nov in Madrid (UTC+1 in winter).
    expect(todayInMadrid(new Date("2026-11-21T23:30:00Z"))).toBe("2026-11-22");
    expect(todayInMadrid(new Date("2026-11-21T22:30:00Z"))).toBe("2026-11-21");
  });
});

describe("durationMs", () => {
  it("reads the play frame token both as written and as minified", () => {
    expect(durationMs("800ms")).toBe(800);
    expect(durationMs(".8s")).toBe(800);
    expect(durationMs(" 1.5s ")).toBe(1500);
    expect(() => durationMs("")).toThrow();
    expect(() => durationMs("fast")).toThrow();
  });
});

describe("trackGeometry", () => {
  const today = "2026-11-22";

  it("keeps a forecast slot of at least the minimum width when the catalogue has no forecast", () => {
    const m = model([["snow_obs", "2026-11-20", "observed"]], today);
    const g = trackGeometry(m, 600, 64);
    expect(g.slotPx).toBe(64);
    expect(g.pastPx).toBe(536);
    expect(g.x(0)).toBe(0);
    expect(g.x(m.todayIndex + 1)).toBe(536);
    // Every position in the slot maps back to today: there is no forecast day to pick.
    expect(g.dayAt(560)).toBe(m.todayIndex);
    expect(g.dayAt(599)).toBe(m.todayIndex);
  });

  it("maps every past pixel to a day and back, in order", () => {
    const m = model([["snow_obs", "2026-11-20", "observed"]], today);
    const g = trackGeometry(m, 600, 64);
    let previous = -1;
    for (let px = 0; px < g.pastPx; px += 0.5) {
      const day = g.dayAt(px);
      expect(day).toBeGreaterThanOrEqual(previous);
      previous = day;
    }
    expect(previous).toBe(m.todayIndex);
    for (const i of [0, 100, m.todayIndex]) expect(g.dayAt(g.x(i + 0.5))).toBe(i);
  });

  it("puts forecast days inside the slot and lets it grow with them, up to half the track", () => {
    const m = model(
      [
        ["snow_obs", "2026-11-20", "observed"],
        ["snow_depth", "2026-11-27", "forecast"],
      ],
      today,
    );
    const g = trackGeometry(m, 600, 64);
    expect(g.slotPx).toBe(64);
    for (let k = 1; k <= 5; k++) {
      const i = m.todayIndex + k;
      expect(g.x(i + 0.5)).toBeGreaterThan(g.pastPx);
      expect(g.dayAt(g.x(i + 0.5))).toBe(i);
    }
    expect(g.x(m.days.length)).toBe(600);
    const wide = trackGeometry(m, 600, 400);
    expect(wide.slotPx).toBe(300);
  });

  it("survives a track that has not been measured yet", () => {
    const m = model([["snow_obs", "2026-11-20", "observed"]], today);
    const g = trackGeometry(m, 0, 64);
    expect(g.slotPx).toBe(0);
    expect(g.dayAt(0)).toBe(0);
  });
});

describe("spreadLabels", () => {
  it("keeps every label when there is room", () => {
    const labels = [0, 40, 80].map((x) => ({ x, wide: false }));
    expect(spreadLabels(labels, 10, 32, 4)).toHaveLength(3);
  });

  it("drops initials that touch the year label and keeps the year", () => {
    const labels = [
      { x: 0, wide: false },
      { x: 12, wide: false },
      { x: 30, wide: true },
      { x: 60, wide: false },
    ];
    const kept = spreadLabels(labels, 10, 32, 4);
    expect(kept.map((l) => l.x)).toEqual([0, 30, 60]);
  });
});
