// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { resolveHorizon, weatherOverlay, type WeatherManifest, type WeatherModel } from "./weather";

const field = (available: boolean) => ({
  available,
  visualization: available
    ? {
        asset: { path: "m/a.png", bytes: 1, sha256: "x" },
        bounds: [-3, 36, -2, 37] as [number, number, number, number],
        scale_min_mm: 0,
        scale_max_mm: 3,
        region_max_mm: 1,
      }
    : undefined,
});
const horizon = (available: boolean) => ({
  valid_at: "2026-11-23T06:00:00Z",
  precipitation_total: field(available),
  snowfall: field(false),
});
const model: WeatherModel = {
  id: "aemet",
  name: "AEMET",
  attribution: "a",
  run_at: "2026-11-22T00:00:00Z",
  source: "s",
  grid_degrees: 0.025,
  horizons: { "24": horizon(true), "48": horizon(true), "72": horizon(false), "120": horizon(false) },
};
const manifest: WeatherManifest = {
  schema_version: 2,
  generated_at: null,
  common_horizons_hours: [24],
  models: [model],
};

describe("resolveHorizon", () => {
  it("keeps an available horizon", () => {
    expect(resolveHorizon(model, "precipitation_total", 48)).toBe(48);
  });
  it("falls back to the shortest available one", () => {
    expect(resolveHorizon(model, "precipitation_total", 120)).toBe(24);
  });
  it("returns null when nothing is available", () => {
    expect(resolveHorizon(model, "snowfall", 24)).toBeNull();
    expect(resolveHorizon(undefined, "snowfall", 24)).toBeNull();
  });
});

describe("weatherOverlay", () => {
  it("resolves the image against the manifest url", () => {
    const o = weatherOverlay(manifest, "aemet", "precipitation_total", 24, "https://x.test/NivoSense/weather/manifest.json");
    expect(o?.imageUrl).toBe("https://x.test/NivoSense/weather/m/a.png");
  });
  it("is null without a horizon or for an unavailable field", () => {
    expect(weatherOverlay(manifest, "aemet", "precipitation_total", null, "/w/manifest.json")).toBeNull();
    expect(weatherOverlay(manifest, "aemet", "precipitation_total", 72, "/w/manifest.json")).toBeNull();
  });
});
