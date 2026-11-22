// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import {
  defaultSelection,
  resolutionLabel,
  resolveHorizon,
  weatherOverlay,
  type WeatherManifest,
  type WeatherModel,
} from "./weather";

const field = (available: boolean, regionMax = 1, units = "mm") => ({
  available,
  units,
  visualization: available
    ? {
        asset: { path: "m/a.png", bytes: 1, sha256: "x" },
        bounds: [-3, 36, -2, 37] as [number, number, number, number],
        scale_min: 0,
        scale_max: 3,
        region_min: 0,
        region_max: regionMax,
      }
    : undefined,
});
const horizon = (available: boolean, rain = 1) => ({
  valid_at: "2026-11-23T06:00:00Z",
  precipitation_total: field(available, rain),
  temperature_2m: field(available, 19, "°C"),
  wind_speed_10m: field(false),
});
const model: WeatherModel = {
  id: "aemet",
  name: "AEMET",
  attribution: "a",
  run_at: "2026-11-22T00:00:00Z",
  source: "s",
  grid_degrees: 0.025,
  resolution_km: 2.5,
  horizons: { "24": horizon(true), "48": horizon(true), "72": horizon(false), "120": horizon(false) },
};
const dryModel: WeatherModel = {
  ...model,
  horizons: { ...model.horizons, "24": horizon(true, 0), "48": horizon(true, 0.4) },
};
const manifest: WeatherManifest = {
  schema_version: 2,
  generated_at: null,
  common_horizons_hours: [24],
  models: [model, dryModel],
};

describe("resolveHorizon", () => {
  it("keeps an available horizon", () => {
    expect(resolveHorizon(model, "precipitation_total", 48)).toBe(48);
  });
  it("falls back to the shortest available one", () => {
    expect(resolveHorizon(model, "precipitation_total", 120)).toBe(24);
  });
  it("returns null when nothing is available", () => {
    expect(resolveHorizon(model, "wind_speed_10m", 24)).toBeNull();
    expect(resolveHorizon(undefined, "wind_speed_10m", 24)).toBeNull();
  });
});

describe("defaultSelection", () => {
  it("opens on precipitation when it has data at the shortest horizon", () => {
    expect(defaultSelection(model)).toEqual({ variable: "precipitation_total", horizon: 24 });
  });
  it("skips a dry precipitation field for temperature instead of a transparent map", () => {
    expect(defaultSelection(dryModel)).toEqual({ variable: "temperature_2m", horizon: 24 });
  });
  it("is null without a model", () => {
    expect(defaultSelection(undefined)).toBeNull();
  });
});

describe("weatherOverlay", () => {
  it("resolves the image against the manifest url and states the resolution", () => {
    const o = weatherOverlay(manifest, "aemet", "precipitation_total", 24, "https://x.test/NivoSense/weather/manifest.json");
    expect(o?.imageUrl).toBe("https://x.test/NivoSense/weather/m/a.png");
    expect(o?.resolution).toBe("0,025° (~2,5 km)");
    expect(o?.dry).toBe(false);
  });
  it("flags dry precipitation but never dry temperature", () => {
    const rain = weatherOverlay({ ...manifest, models: [dryModel] }, "aemet", "precipitation_total", 24, "/w/manifest.json");
    const temperature = weatherOverlay({ ...manifest, models: [dryModel] }, "aemet", "temperature_2m", 24, "/w/manifest.json");
    expect(rain?.dry).toBe(true);
    expect(temperature?.dry).toBe(false);
  });
  it("is null without a horizon or for an unavailable field", () => {
    expect(weatherOverlay(manifest, "aemet", "precipitation_total", null, "/w/manifest.json")).toBeNull();
    expect(weatherOverlay(manifest, "aemet", "precipitation_total", 72, "/w/manifest.json")).toBeNull();
  });
});

describe("resolutionLabel", () => {
  it("shows degrees and kilometres", () => {
    expect(resolutionLabel({ grid_degrees: 0.1, resolution_km: 10 })).toBe("0,10° (~10 km)");
  });
});
