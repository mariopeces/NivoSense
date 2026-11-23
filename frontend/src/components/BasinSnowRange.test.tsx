// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import "../test/dom";
import type { CatalogEntry } from "../lib/catalog";
import { snowRanges } from "../lib/snowRange";
import BasinSnowRange from "./BasinSnowRange";

const scores = {
  basin_604456_snow_area_km2_p10: 121.8,
  basin_604456_snow_area_km2_p50: 200.8,
  basin_604456_snow_area_km2_p90: 296.3,
  basin_604456_depth_mean_m_p10: 0.102,
  basin_604456_depth_mean_m_p50: 0.197,
  basin_604456_depth_mean_m_p90: 0.477,
  basin_604456_depth_peak_m_p10: 0.456,
  basin_604456_depth_peak_m_p50: 1.187,
  basin_604456_depth_peak_m_p90: 2.328,
};
const entry = {
  layer: "snow_depth",
  date: "2025-02-11",
  status: "modelled",
  cog: "layers/snow_depth/2025/x.tif",
  pmtiles: "tiles/snow_depth/x.pmtiles",
  bounds: [-3.6, 36.9, -2.6, 37.3],
  resolution_m: 100,
  bands: ["depth_p50", "depth_p10", "depth_p90"],
  units: ["m", "m", "m"],
  source_ids: ["x"],
  qa: { flags: [], scores },
} as CatalogEntry;

describe("snowRanges", () => {
  it("reads the p10, p50 and p90 of a group and converts the depth to centimetres", () => {
    const ranges = snowRanges(entry, "basin_604456");
    expect(ranges?.area).toEqual({ p10: 121.8, p50: 200.8, p90: 296.3 });
    expect(ranges?.meanDepth.p50).toBeCloseTo(19.7);
    expect(ranges?.peakDepth.p90).toBeCloseTo(232.8);
  });

  it("is null when the group, the scores or the entry are missing", () => {
    expect(snowRanges(entry, "basin_1")).toBeNull();
    expect(snowRanges({ ...entry, qa: undefined }, "basin_604456")).toBeNull();
    expect(snowRanges(null, "domain")).toBeNull();
  });
});

describe("BasinSnowRange", () => {
  it("shows the median and the range of the basin as a model estimate, with the date", () => {
    render(<BasinSnowRange entry={entry} basinId="604456" />);
    const card = within(screen.getByRole("region", { name: "Nieve del modelo este día" }));
    expect(card.getByText("201 km² (de 122 a 296)")).toBeTruthy();
    expect(card.getByText("20 cm (de 10 a 48)")).toBeTruthy();
    expect(card.getByText("119 cm (de 46 a 233)")).toBeTruthy();
    expect(card.getByText(/sin validar con medidas de campo/)).toBeTruthy();
    expect(card.getByText(/11 feb 2025/)).toBeTruthy();
  });

  it("says there is no estimate for a basin or a day the entry does not cover", () => {
    render(<BasinSnowRange entry={null} basinId="604456" />);
    expect(screen.getByText("El modelo no tiene estimación para esta cuenca este día.")).toBeTruthy();
  });
});
