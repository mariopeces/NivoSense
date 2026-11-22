// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import fixture from "../test/fixtures/catalog-t04-evidence-98f90df.json";
import { parseCatalog, type CatalogEntry } from "./catalog";
import { LAYER_SPECS, RAMPS, catalogRoot, entryFor, layerSpecs, pmtilesUrl, rampBounds } from "./layers";

// A real catalogue: written by publish() to the staging scratch prefix during the T0.4 evidence run, 7 true
// colour entries between 24 Oct and 20 Nov 2026.
const index = parseCatalog(fixture);
const rgb = index.layers.rgb.entries;

describe("layerSpecs", () => {
  it("lists every layer the pipelines publish, true colour last", () => {
    expect(LAYER_SPECS.map((spec) => spec.id)).toEqual(["snow_obs", "snow_gapfill", "swe", "snow_depth", "rgb"]);
    expect(LAYER_SPECS[LAYER_SPECS.length - 1].group).toBe("imagen");
  });

  it("gives every snow layer a ramp that exists, and the true colour none", () => {
    for (const spec of LAYER_SPECS) {
      if (spec.id === "rgb") expect(spec.ramp).toBeNull();
      else expect(RAMPS[spec.ramp ?? ""], spec.id).toBeTruthy();
    }
  });

  it("adds a row for a catalogued layer it does not know, so every layer stays reachable", () => {
    const extra = { ...index, layers: { ...index.layers, wet_snow: { dates: [], entries: [] } } };
    const specs = layerSpecs(extra);
    expect(specs.map((spec) => spec.id)).toEqual([...LAYER_SPECS.map((spec) => spec.id), "wet_snow"]);
    expect(specs[specs.length - 1]).toEqual({ id: "wet_snow", copy: "", ramp: null, group: "nieve" });
    expect(layerSpecs(null)).toEqual(LAYER_SPECS);
  });
});

describe("entryFor", () => {
  it("returns the entry of the day when there is one", () => {
    expect(entryFor(rgb, "2026-11-10")).toEqual({ entry: rgb.find((e) => e.date === "2026-11-10"), exact: true });
  });

  it("never borrows the nearest day for a modelled layer", () => {
    const modelled: CatalogEntry[] = [{ ...rgb[0], layer: "swe", status: "modelled", date: "2026-11-10" }];
    expect(entryFor(modelled, "2026-11-10")?.exact).toBe(true);
    expect(entryFor(modelled, "2026-11-11")).toBeNull();
  });

  it("otherwise the nearest entry, the earlier one on a tie", () => {
    // 2026-11-10 and 2026-11-13 are 3 days apart: 11-11 is nearer the first, 11-12 nearer the second.
    expect(entryFor(rgb, "2026-11-11")?.entry.date).toBe("2026-11-10");
    expect(entryFor(rgb, "2026-11-12")?.entry.date).toBe("2026-11-13");
    expect(entryFor(rgb, "2026-11-12")?.exact).toBe(false);
    const tie: CatalogEntry[] = [
      { ...rgb[0], date: "2026-01-03" },
      { ...rgb[0], date: "2026-01-01" },
    ];
    expect(entryFor(tie, "2026-01-02")?.entry.date).toBe("2026-01-01");
    expect(entryFor(rgb, "2025-10-01")?.entry.date).toBe("2026-10-24");
  });

  it("is null for a layer with no entries", () => {
    expect(entryFor([], "2026-11-10")).toBeNull();
  });
});

describe("catalogue URLs", () => {
  it("resolves entry keys against the folder that holds catalog/index.json", () => {
    const root = catalogRoot("https://storage.googleapis.com/nivosense-cogs/staging/catalog/index.json");
    expect(root).toBe("https://storage.googleapis.com/nivosense-cogs/staging/");
    expect(pmtilesUrl(root, rgb[0])).toBe(
      "pmtiles://https://storage.googleapis.com/nivosense-cogs/staging/tiles/rgb/2026-10-24-4b64a9a0550ae0be.pmtiles",
    );
  });
});

describe("rampBounds", () => {
  it("labels every class start and a closed last class end", () => {
    expect(rampBounds(RAMPS.swe)).toEqual([0, 5, 25, 50, 100, 200, 400, 800]);
    expect(rampBounds(RAMPS.snow_cover_probability)).toEqual([0, 0.1, 0.3, 0.5, 0.7, 0.9]);
    expect(rampBounds({ ...RAMPS.swe, classes: RAMPS.swe.classes.slice(0, 2) })).toEqual([0, 5, 25]);
  });
});
