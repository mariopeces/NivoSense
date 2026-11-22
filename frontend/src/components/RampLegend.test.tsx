// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import "../test/dom";
import { RAMPS } from "../lib/layers";
import RampLegend from "./RampLegend";

// The legend must draw exactly the classes pipelines/ramps.py paints: same colours, same alphas, same bounds.
describe("RampLegend", () => {
  it.each(["swe", "snow_depth", "snow_cover_probability"])("draws every %s class with its colour and alpha", (id) => {
    const { container } = render(<RampLegend rampId={id} />);
    const steps = [...container.querySelectorAll<HTMLSpanElement>("[aria-hidden=true] > span.flex-1")];
    const ramp = RAMPS[id];
    expect(steps).toHaveLength(ramp.classes.length);
    steps.forEach((step, i) => {
      const cls = ramp.classes[i];
      if (cls.color === null) {
        expect(step.style.backgroundColor).toBe("");
      } else {
        const n = parseInt(cls.color.slice(1), 16);
        // jsdom normalises the colour to its channels; compare the numbers.
        expect(step.style.backgroundColor.match(/\d+/g)?.map(Number)).toEqual([n >> 16, (n >> 8) & 255, n & 255]);
        expect(Number(step.style.opacity)).toBe(cls.alpha);
      }
    });
    const labels = [...container.querySelectorAll(".tnum span")].map((s) => s.textContent);
    const last = ramp.classes[ramp.classes.length - 1].max;
    const bounds = [...ramp.classes.map((c) => c.min ?? 0), ...(last == null ? [] : [last])];
    expect(labels).toEqual(bounds.map((b) => String(Math.round(ramp.unit === "%" ? b * 100 : b))));
  });

  it("draws each observed-snow class swatch with its fill, alpha and pattern", () => {
    const { container } = render(<RampLegend rampId="snow_cover_observed" />);
    const items = [...container.querySelectorAll("li")];
    expect(items.map((li) => li.textContent)).toEqual(RAMPS.snow_cover_observed.classes.map((c) => c.label_es));
    RAMPS.snow_cover_observed.classes.forEach((cls, i) => {
      const fill = items[i].querySelector("rect[fill-opacity]");
      if (cls.color) {
        expect(fill?.getAttribute("fill")).toBe(cls.color);
        expect(Number(fill?.getAttribute("fill-opacity"))).toBe(cls.alpha);
      } else {
        expect(fill).toBeNull();
      }
      const pattern = items[i].querySelector("g");
      expect(pattern?.getAttribute("fill") ?? null).toBe(cls.pattern?.color ?? null);
      if (cls.pattern?.kind === "dots") expect(pattern?.querySelectorAll("circle").length).toBeGreaterThan(0);
      if (cls.pattern?.kind === "hatch") expect(pattern?.querySelectorAll("line").length).toBeGreaterThan(0);
    });
  });
});
