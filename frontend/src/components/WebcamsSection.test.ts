import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import type { Webcam } from "../lib/types";
import { byRoadPoint, cameraName, placeName } from "./WebcamsSection";

const catalogue: Webcam[] = JSON.parse(
  readFileSync(path.resolve(__dirname, "../../public/data/webcams.json"), "utf8"),
);

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
