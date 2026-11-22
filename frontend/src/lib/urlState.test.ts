import { describe, expect, it } from "vitest";
import { readUrlState, writeUrlState } from "./urlState";

describe("URL state", () => {
  it("reads the date and the visible layers with their opacity", () => {
    expect(readUrlState("?d=2026-02-21&l=rgb:100,snow_obs:80")).toEqual({
      date: "2026-02-21",
      layers: [
        { id: "rgb", opacity: 100 },
        { id: "snow_obs", opacity: 80 },
      ],
    });
    expect(readUrlState("")).toEqual({ date: null, layers: [] });
  });

  it("puts a layer without an opacity at 100, and keeps a link from before opacities existed", () => {
    expect(readUrlState("?l=swe").layers).toEqual([{ id: "swe", opacity: 100 }]);
  });

  it("drops dates that are not on the calendar and malformed, repeated or out-of-range layers", () => {
    expect(readUrlState("?d=2026-02-30").date).toBeNull();
    expect(readUrlState("?d=21-02-2026").date).toBeNull();
    expect(readUrlState("?l=<script>,Swe,rgb:101,rgb:-1,rgb:50,rgb:60").layers).toEqual([{ id: "rgb", opacity: 50 }]);
  });

  it("writes date and layers readably and keeps other parameters", () => {
    expect(
      writeUrlState("?x=1", {
        date: "2026-02-21",
        layers: [
          { id: "rgb", opacity: 100 },
          { id: "snow_obs", opacity: 80 },
        ],
      }),
    ).toBe("?x=1&d=2026-02-21&l=rgb:100,snow_obs:80");
    expect(writeUrlState("?d=2026-02-21&l=swe", { date: "2026-03-01", layers: [] })).toBe("?d=2026-03-01");
    expect(writeUrlState("?d=2026-02-21", { date: null, layers: [] })).toBe("");
  });

  it("round-trips", () => {
    const state = { date: "2025-10-01", layers: [{ id: "snow_depth", opacity: 35 }] };
    expect(readUrlState(writeUrlState("", state))).toEqual(state);
  });
});
