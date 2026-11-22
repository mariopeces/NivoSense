// Gauntlet T0.6 round 4 probes: every line below must be reported by local/no-hard-coded-colour.
import type { CSSProperties } from "react";

declare const H: string;
declare const x: string;
declare const suffix: string;
declare const t: boolean;
declare const map: { setPaintProperty(a: string, b: string, c: unknown): void };

// (1) named colour as a var() fallback in style strings
export const v1 = { color: "var(--x, red)", background: "var(--a, var(--b, gold))", borderColor: `var(--x, ${"navy"})` };
document.body.style.color = "var(--x, tomato)";

// (2) MapLibre legacy function default/stops and expression fallbacks
export const m1 = { "fill-color": { type: "categorical", property: "k", default: "crimson", stops: [["a", "#00ff00"]] } };
export const m2 = { "line-color": { property: "k", stops: [[0, "teal"]] } };
export const m3 = { "fill-color": ["match", ["get", "k"], "a", "#ffffff", "salmon"] };
export const m4 = { "circle-color": ["coalesce", ["get", "c"], "orchid"] };
export const m5 = { "fill-color": t ? { type: "interval", property: "k", default: "plum" } : "#abcdef" };
map.setPaintProperty("l", "fill-color", { property: "k", type: "categorical", default: "sienna" });

// (3) hex built from template pieces
export const h1 = `#${H}`;
export const h2 = `#${`ff0000`}`;
export const h3 = `#${"ff0001"}${suffix}`;
export const h4 = `#${x}ff0000`;
export const h5 = `\x23${x}ff00`;
export const h6 = `${`${`#f0f`}`}`;
export const h7 = `#${t ? `ff0000` : `00ff00`}`;

// (4) colour-bearing shorthands and composites, camelCase and kebab, custom-property keys
export const s1 = (
  <div
    style={
      {
        background: "maroon",
        border: "1px solid olive",
        borderInlineStart: "1px solid lime",
        outline: "1px solid aqua",
        boxShadow: "0 0 1px peru",
        textShadow: "0 0 1px tan",
        textDecoration: "underline wavy coral",
        filter: "drop-shadow(0 0 1px khaki)",
        backdropFilter: "drop-shadow(0 0 1px linen)",
        columnRule: "1px solid wheat",
        caretColor: "azure",
        accentColor: "beige",
        fill: "ivory",
        stroke: "indigo",
        "--accent": "orange",
        ["--glow" as string]: "pink",
      } as CSSProperties
    }
  />
);
export const s2 = { "box-shadow": "0 0 1px snow", "text-decoration": "underline thistle", "column-rule": "1px solid bisque" };

// Round 3 bypasses (G-Infra probe and G-Code items 2 and 3)
export const r1 = <div style={{ "--accent": "red", textDecoration: "underline red", color: `#${`00ff00`}`, background: `#${H}` } as CSSProperties} />;
export const r2 = `#${x}ff00`;
export const r3 = <div style={{ textDecoration: "underline wavy red", filter: "drop-shadow(0 0 2px red)", columnRule: "1px solid red" }} />;

// Minor (not expected to be caught): a template-literal computed key
export const k1 = { [`--accent`]: "fuchsia" };
