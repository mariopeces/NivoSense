import { describe, expect, it } from "vitest";
import type { Webcam } from "./types";
import { byRoadPoint, cameraName, captureAge, fanOffsets, groupRadiusM, groupWebcams, isLive, placeName } from "./webcams";

const cam = (name: string, extra: Partial<Webcam> = {}): Webcam => ({
  id: name,
  name,
  location: "GRANADA",
  provider: "DGT",
  latitude: 37.1,
  longitude: -3.4,
  position_source: null,
  thumbnail_url: null,
  large_url: null,
  captured_at: null,
  status: "offline",
  source_url: "https://example.org",
  attribution: "DGT",
  ...extra,
});

describe("webcam names", () => {
  it("writes DGT road points with a decimal comma and places in title case", () => {
    expect(cameraName("A-395 · PK 12.6")).toBe("A-395 · PK 12,6");
    expect(placeName("GRANADA")).toBe("Granada");
    expect(placeName("Pradollano")).toBe("Pradollano");
  });

  it("sorts along the road", () => {
    const sorted = ["A-395 · PK 24.95", "A-395 · PK 7.8", "A-395 · PK 12.6"].map((n) => cam(n)).sort(byRoadPoint);
    expect(sorted.map((c) => c.name)).toEqual(["A-395 · PK 7.8", "A-395 · PK 12.6", "A-395 · PK 24.95"]);
  });
});

describe("groupWebcams", () => {
  it("puts cameras within 30 m in one group and leaves distant ones alone", () => {
    const groups = groupWebcams([
      cam("a", { latitude: 37.0711, longitude: -3.3894 }),
      cam("b", { latitude: 37.0711, longitude: -3.3894 }),
      cam("c", { latitude: 37.07123, longitude: -3.3894 }), // about 14 m north
      cam("far", { latitude: 37.0826, longitude: -3.4059 }),
    ]);
    expect(groups.map((g) => g.cams.map((c) => c.id))).toEqual([["a", "b", "c"], ["far"]]);
  });

  it("splits cameras 60 m apart", () => {
    expect(groupWebcams([cam("a"), cam("b", { latitude: 37.1006 })])).toHaveLength(2);
  });

  it("drops cameras without a position", () => {
    expect(groupWebcams([cam("a", { latitude: null, longitude: null }), cam("b")])).toHaveLength(1);
  });
});

describe("groupRadiusM", () => {
  it("keeps 30 m when zoomed in and widens to the overlap distance when zoomed out", () => {
    expect(groupRadiusM(17, 37)).toBe(30);
    const wide = groupRadiusM(9, 37);
    expect(wide).toBeGreaterThan(2000);
    expect(groupRadiusM(10, 37)).toBeCloseTo(wide / 2, 0);
  });

  it("merges two stations 2 km apart only when zoomed out", () => {
    const stations = [cam("a"), cam("b", { latitude: 37.1 + 2000 / 111_320 })];
    expect(groupWebcams(stations, groupRadiusM(9, 37))).toHaveLength(1);
    expect(groupWebcams(stations, groupRadiusM(13, 37))).toHaveLength(2);
  });
});

describe("fanOffsets", () => {
  it("starts upwards and spreads n points in distinct directions on one circle", () => {
    const offsets = fanOffsets(5);
    expect(offsets[0]).toMatchObject({ dx: 0, dy: -offsets[0].radius });
    expect(new Set(offsets.map((o) => Math.round(Math.hypot(o.dx, o.dy)))).size).toBe(1);
    expect(new Set(offsets.map((o) => `${o.dx},${o.dy}`)).size).toBe(5);
  });

  it("keeps neighbours about the spacing apart", () => {
    const offsets = fanOffsets(9, 44);
    for (let i = 0; i < offsets.length; i++) {
      const next = offsets[(i + 1) % offsets.length];
      expect(Math.hypot(next.dx - offsets[i].dx, next.dy - offsets[i].dy)).toBeGreaterThanOrEqual(40);
    }
  });
});

describe("capture age and state", () => {
  const at = "2026-11-22T00:25:00Z";
  it("words the age against the clock", () => {
    expect(captureAge(at, Date.parse("2026-11-22T00:25:30Z"))).toBe("hace menos de 1 min");
    expect(captureAge(at, Date.parse("2026-11-22T01:06:00Z"))).toBe("hace 41 min");
    expect(captureAge(at, Date.parse("2026-11-22T04:30:00Z"))).toBe("hace 4 h");
    expect(captureAge(at, Date.parse("2026-11-24T04:30:00Z"))).toBe("hace 2 días");
  });

  it("counts a camera as live only with a status live and a checked still", () => {
    const still = "data/webcam-stills/x/20261122T000000Z-large-abc.jpg";
    expect(isLive(cam("a", { status: "live", large_url: still }))).toBe(true);
    expect(isLive(cam("a", { status: "live", large_url: "https://evil.example/x.jpg" }))).toBe(false);
    expect(isLive(cam("a", { status: "offline", large_url: still }))).toBe(false);
  });
});
