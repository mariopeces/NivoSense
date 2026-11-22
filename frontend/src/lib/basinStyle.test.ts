import { describe, expect, it } from "vitest";
import { basinStyle } from "./basinStyle";

describe("basinStyle", () => {
  it("draws filled, selectable basins on the Agua tab", () => {
    const s = basinStyle("agua");
    expect(s.fillOpacity).toBeGreaterThan(0);
    expect(s.interactive).toBe(true);
  });

  it.each(["nieve", "webcams", "meteo", "metodo"])("only a thin outline on %s", (section) => {
    const s = basinStyle(section);
    expect(s.fillOpacity).toBe(0);
    expect(s.interactive).toBe(false);
    expect(s.lineWidth).toBeLessThan(basinStyle("agua").lineWidth);
  });
});
