import css from "@eslint/css";
import { RuleTester } from "eslint";
import tseslint from "typescript-eslint";
import { describe, it } from "vitest";
import rule from "./no-hard-coded-colour.js";

RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const tokensFile = "src/styles/tokens.css";
const file = "src/Probe.tsx";
const options = (baseline = {}, extra = {}) => [{ tokensFile, baseline, ...extra }];
const colour = (value) => ({ messageId: "colour", data: { value, tokensFile } });
// With inline config off, as in eslint.config.js, ESLint warns that the directive has no effect.
const ignored = { message: /has no effect because you have 'noInlineConfig'/ };
const jsx = { parserOptions: { ecmaFeatures: { jsx: true } } };

new RuleTester({ languageOptions: jsx, linterOptions: { noInlineConfig: true } }).run("no-hard-coded-colour in scripts", rule, {
  valid: [
    { filename: file, code: 'const a = "bg-navy text-slate-100 #section";', options: options() },
    { filename: file, code: 'const a = "S2 RGB", b = "true colour";', options: options() },
    // Named colours in prose and identifiers are words, not colours.
    { filename: file, code: 'const red = "La nieve en Sierra Nevada es white y red";', options: options() },
    { filename: file, code: 'const a = { "fill-color": "var(--colour-snow)" };', options: options() },
    { filename: file, code: 'const a = "bg-[#081020]";', options: options({ [file]: { "#081020": 1 } }) },
  ],
  invalid: [
    { filename: file, code: 'const a = "#ABCDEF";', options: options(), errors: [colour("#abcdef")] },
    {
      filename: file,
      code: "const a = `shadow-[0_0_8px_RGBA(34, 211, 238, 0.5)] ${b}`;",
      options: options(),
      errors: [colour("rgba(34,211,238,0.5)")],
    },
    {
      filename: file,
      code: 'const a = ["hsl(10 20% 30%)", "oklch(70% 0.1 200)", "#abcd", "#11223344", "hwb(1 2% 3%)", "lab(1 2 3)"];',
      options: options(),
      errors: [
        colour("hsl(10 20% 30%)"),
        colour("oklch(70% 0.1 200)"),
        colour("#abcd"),
        colour("#11223344"),
        colour("hwb(1 2% 3%)"),
        colour("lab(1 2 3)"),
      ],
    },
    {
      // Template literals: colour parts around interpolations, literal interpolations and escape sequences.
      filename: file,
      code: [
        "const a = `rgb(${r}, 0, 0)`;",
        "const b = `#ff${x}`;",
        'const c = `#${"ff00ff"}`;',
        "const d = `border-[\\u0023abcdef] ${y}`;",
        'const e = "\\x23123456";',
      ].join("\n"),
      options: options(),
      errors: [colour("rgb(${},0,0)"), colour("#ff${}"), colour("#ff00ff"), colour("#abcdef"), colour("#123456")],
    },
    {
      // A hex built from pieces: `#` or partial digits before an interpolation, nested static templates, literal
      // interpolations next to dynamic ones.
      filename: file,
      code: [
        "const a = `#${H}`;",
        "const b = `#${`ff0000`}`;",
        'const c = `#${"ff0000"}${suffix}`;',
        "const d = `#${x}ff0000`;",
        "const e = `\x23${x}ff00`;",
        "const f = `${`#00ff00`}`;",
      ].join("\n"),
      options: options(),
      errors: [colour("#${}"), colour("#ff0000"), colour("#ff0000"), colour("#${}"), colour("#${}"), colour("#00ff00")],
    },
    {
      // Named colours as var() fallbacks, in custom properties and in colour shorthands and composites.
      filename: "src/Probe.jsx",
      code: [
        'const a = <div style={{ color: "var(--x, red)", "--accent": "blue" }} />;',
        'const b = { textDecoration: "underline gold", columnRule: "1px solid teal" };',
        'const c = { filter: "drop-shadow(0 0 2px navy)", backdropFilter: "drop-shadow(0 0 1px olive)" };',
        'const d = { caretColor: "lime", accentColor: "plum", textShadow: "0 0 2px tan" };',
      ].join("\n"),
      options: options(),
      errors: ["red", "blue", "gold", "teal", "navy", "olive", "lime", "plum", "tan"].map(colour),
    },
    {
      // A computed custom property key with a cast, as React's style typing needs.
      filename: file,
      code: 'const a = { ["--glow" as string]: "coral" };',
      languageOptions: { parser: tseslint.parser },
      options: options(),
      errors: [colour("coral")],
    },
    {
      // MapLibre legacy functions: colours in `default` and `stops` belong to the paint key; expression fallbacks.
      filename: file,
      code: [
        'const a = { "fill-color": { type: "categorical", property: "k", default: "red", stops: [[1, "#00ff00"]] } };',
        'const b = { "line-color": ["match", ["get", "k"], "a", "#ffffff", "salmon"] };',
        'const c = { "circle-color": ["coalesce", ["get", "c"], "orchid"] };',
      ].join("\n"),
      options: options(),
      errors: [colour("red"), colour("#00ff00"), colour("#ffffff"), colour("salmon"), colour("orchid")],
    },
    {
      // Nested parentheses are matched to the balanced closing one.
      filename: file,
      code: 'const a = ["rgb(calc(255) 0 255)", "rgb(var(--a) / 50%)", "rgba(255,0,255,var(--x))", "color(srgb 1 0 0)"];',
      options: options(),
      errors: [
        colour("rgb(calc(255) 0 255)"),
        colour("rgb(var(--a)/50%)"),
        colour("rgba(255,0,255,var(--x))"),
        colour("color(srgb 1 0 0)"),
      ],
    },
    {
      // Named colours where a value is a colour: style props, SVG and Recharts props, MapLibre paint.
      filename: "src/Probe.jsx",
      code: [
        'const a = <div style={{ borderColor: "magenta", boxShadow: "0 0 4px black" }} />;',
        'const b = <Bar fill="Red" stroke={x ? "blue" : "none"} />;',
        'const c = <stop stopColor="white" />;',
        'const d = { "fill-color": ["case", ["==", ["get", "k"], 1], "tomato", "transparent"] };',
        'map.setPaintProperty("snow", "line-color", "gold");',
        'el.style.backgroundColor = "teal";',
      ].join("\n"),
      options: options(),
      errors: ["magenta", "black", "red", "blue", "white", "tomato", "gold", "teal"].map(colour),
    },
    {
      filename: file,
      code: 'const a = { "circle-color": ["rgb", 255, 0, 255] };',
      options: options(),
      errors: [colour('["rgb",255,0,255]')],
    },
    {
      filename: "tailwind.config.js",
      code: 'export default { theme: { extend: { colors: { brand: "magenta" } } } };',
      options: options({}, { namedColoursAnywhere: true }),
      errors: [colour("magenta")],
    },
    {
      // A second colour inside a literal whose first colour is in the baseline.
      filename: file,
      code: 'const a = "bg-[#081020] text-[#ff00ff]";',
      options: options({ [file]: { "#081020": 1 } }),
      errors: [colour("#ff00ff")],
    },
    {
      // A swapped colour is new, and the one it replaced leaves a stale baseline entry.
      filename: file,
      code: 'const a = "bg-[#ff00ff]";',
      options: options({ [file]: { "#081020": 1 } }),
      errors: [{ messageId: "stale" }, colour("#ff00ff")],
    },
    {
      // The baseline is per file: a colour listed for another file is new here.
      filename: file,
      code: 'const a = "#081020";',
      options: options({ "src/Other.tsx": { "#081020": 1 } }),
      errors: [colour("#081020")],
    },
    {
      filename: file,
      code: '// eslint-disable-next-line rule-to-test/no-hard-coded-colour\nconst a = 1;\n/* eslint-disable */\nconst b = 2;',
      options: options(),
      errors: [ignored, { messageId: "directive" }, ignored, { messageId: "directive" }],
    },
  ],
});

new RuleTester({
  plugins: { css },
  language: "css/css",
  languageOptions: { tolerant: true },
  linterOptions: { noInlineConfig: true },
}).run(
  "no-hard-coded-colour in stylesheets",
  rule,
  {
    valid: [
      {
        filename: "src/a.css",
        code: "#root { color: var(--colour-text); background: transparent; animation: snow 1s; --red-ish: var(--red); }",
        options: options(),
      },
      { filename: "src/a.css", code: ".a { color: #081020; }", options: options({ "src/a.css": { "#081020": 1 } }) },
    ],
    invalid: [
      {
        filename: "src/a.css",
        code: ".a { color: #FF00FF; border: 1px solid rgba(1, 2, 3, .5); outline-color: Red; }",
        options: options(),
        errors: [colour("#ff00ff"), colour("rgba(1,2,3,.5)"), colour("red")],
      },
      {
        // Custom properties are where tokens live: outside the tokens file they cannot hold colours.
        filename: "src/a.css",
        code: ":root { --a: #fff; --b: rgb(255 0 255); --c: red; --d: rgb(var(--a) / 50%); }",
        options: options(),
        errors: [colour("#fff"), colour("rgb(255 0 255)"), colour("red"), colour("rgb(var(--a)/50%)")],
      },
      {
        filename: "src/a.css",
        code: `.a { color: rgb(calc(255) 0 255); background: url("data:image/svg+xml,%3Csvg fill='%23ff00ff'/%3E"); }`,
        options: options(),
        errors: [colour("rgb(calc(255) 0 255)"), colour("#ff00ff")],
      },
      {
        filename: "src/a.css",
        code: ".a { color: var(--x, red); background: var(--y,blue); border-color: var(--a, var(--b, gold)); }",
        options: options(),
        errors: [colour("red"), colour("blue"), colour("gold")],
      },
      {
        filename: "src/a.css",
        code: ".a { @apply bg-[#123456]; }",
        options: options(),
        errors: [colour("#123456")],
      },
      {
        filename: "src/a.css",
        code: "/* eslint-disable */\n.a { color: blue; }",
        options: options(),
        errors: [ignored, { messageId: "directive" }, colour("blue")],
      },
    ],
  },
);
