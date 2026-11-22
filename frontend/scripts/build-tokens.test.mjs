import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { TOKENS_CSS, TOKENS_JSON, flattenTokens, renderTokensCss } from "./build-tokens.mjs";

const tokens = JSON.parse(readFileSync(TOKENS_JSON, "utf8"));

describe("design tokens", () => {
  it("committed tokens.css matches tokens.json (run npm run tokens)", () => {
    expect(readFileSync(TOKENS_CSS, "utf8")).toBe(renderTokensCss(tokens));
  });

  it("names every colour --color-<name> and every type style by size, line height and weight", () => {
    const vars = Object.fromEntries(flattenTokens(tokens));
    for (const [name, token] of Object.entries(tokens.color)) {
      if (!name.startsWith("$")) expect(vars[`color-${name}`]).toBe(token.$value);
    }
    expect(vars["type-caption-size"]).toBe("12px");
    expect(vars["type-title-family"]).toBe("var(--font-family-display)");
    expect(vars["motion-easing-standard"]).toBe("cubic-bezier(0.2, 0, 0, 1)");
  });

  it("drops animation durations under reduced motion but keeps the timeline step", () => {
    const css = renderTokensCss(tokens);
    const reduced = css.slice(css.indexOf("prefers-reduced-motion"));
    expect(reduced).toContain("--motion-duration-panel: 0ms");
    expect(reduced).not.toContain("play-frame");
  });
});
