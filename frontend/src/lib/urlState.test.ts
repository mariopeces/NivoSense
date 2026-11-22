import { describe, expect, it } from "vitest";
import { readUrlState, writeUrlState } from "./urlState";

describe("URL state", () => {
  it("reads the date and the layer", () => {
    expect(readUrlState("?d=2026-02-21&l=swe")).toEqual({ date: "2026-02-21", layer: "swe" });
    expect(readUrlState("")).toEqual({ date: null, layer: null });
  });

  it("drops dates that are not on the calendar and malformed layers", () => {
    expect(readUrlState("?d=2026-02-30").date).toBeNull();
    expect(readUrlState("?d=21-02-2026").date).toBeNull();
    expect(readUrlState("?d=2026-2-1").date).toBeNull();
    expect(readUrlState("?l=<script>").layer).toBeNull();
    expect(readUrlState("?l=Swe").layer).toBeNull();
  });

  it("writes date and layer and keeps other parameters", () => {
    expect(writeUrlState("?x=1", { date: "2026-02-21", layer: "observed_snow_10m" })).toBe(
      "?x=1&d=2026-02-21&l=observed_snow_10m",
    );
    expect(writeUrlState("?d=2026-02-21&l=swe", { date: "2026-03-01", layer: null })).toBe("?d=2026-03-01");
    expect(writeUrlState("?d=2026-02-21", { date: null, layer: null })).toBe("");
  });

  it("round-trips", () => {
    const state = { date: "2025-10-01", layer: "depth" };
    expect(readUrlState(writeUrlState("", state))).toEqual(state);
  });
});
