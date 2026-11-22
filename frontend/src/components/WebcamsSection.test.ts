import { describe, expect, it } from "vitest";
import type { Webcam } from "../lib/types";
import { byRoadPoint, cameraName, placeName } from "./WebcamsSection";

const cam = (name: string): Webcam => ({
  id: name,
  name,
  location: "GRANADA",
  provider: "DGT",
  latitude: null,
  longitude: null,
  position_source: null,
  thumbnail_url: null,
  large_url: null,
  captured_at: null,
  status: "offline",
  source_url: "https://example.org",
  attribution: "DGT",
});
const catalogue: Webcam[] = ["A-395 · PK 24.95", "A-395 · PK 7.8", "A-395 · PK 12.6"].map(cam);

describe("webcam rows", () => {
  it("writes DGT road points with a decimal comma and places in title case", () => {
    expect(cameraName("A-395 · PK 12.6")).toBe("A-395 · PK 12,6");
    expect(cameraName("A-395 · PK 7.8")).toBe("A-395 · PK 7,8");
    expect(placeName("GRANADA")).toBe("Granada");
    expect(placeName("Pradollano")).toBe("Pradollano");
  });

  it("sorts the live catalogue along the road", () => {
    const km = [...catalogue].sort(byRoadPoint).map((cam) => Number(/PK (\S+)/.exec(cam.name)?.[1]));
    expect(km.length).toBe(catalogue.length);
    expect(km).toEqual([...km].sort((a, b) => a - b));
  });
});
