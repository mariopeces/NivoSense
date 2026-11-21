import { describe, expect, it } from "vitest";
import { currentHydrologicalYear, horizonToDate, nextHorizon, previousHorizon } from "./horizons";

describe("currentHydrologicalYear", () => {
  it("rolls over on 1 October", () => {
    expect(currentHydrologicalYear(new Date(2025, 8, 30))).toBe(2025);
    expect(currentHydrologicalYear(new Date(2025, 9, 1))).toBe(2026);
  });
});

describe("horizon stepping", () => {
  it("adds 120 hours for the five-day horizon", () => {
    const now = new Date(Date.UTC(2026, 0, 1, 6));
    expect(horizonToDate("plus5d", now).getTime() - now.getTime()).toBe(120 * 3600 * 1000);
  });

  it("stops at both ends", () => {
    expect(previousHorizon(null)).toBeNull();
    expect(nextHorizon("plus5d")).toBe("plus5d");
    expect(nextHorizon(null)).toBe("plus24h");
  });
});
