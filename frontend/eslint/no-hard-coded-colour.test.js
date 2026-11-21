import css from "@eslint/css";
import { RuleTester } from "eslint";
import { describe, it } from "vitest";
import rule from "./no-hard-coded-colour.js";

RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const tokensFile = "src/styles/tokens.css";
const file = "src/Probe.tsx";
const options = (baseline = {}) => [{ tokensFile, baseline }];
const colour = (value) => ({ messageId: "colour", data: { value, tokensFile } });

new RuleTester().run("no-hard-coded-colour in scripts", rule, {
  valid: [
    { filename: file, code: 'const a = "bg-navy text-slate-100 #section";', options: options() },
    { filename: file, code: 'const a = "S2 RGB", b = "true colour";', options: options() },
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
      code: 'const a = ["hsl(10 20% 30%)", "oklch(70% 0.1 200)", "#abcd", "#11223344"];',
      options: options(),
      errors: [colour("hsl(10 20% 30%)"), colour("oklch(70% 0.1 200)"), colour("#abcd"), colour("#11223344")],
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
  ],
});

new RuleTester({ plugins: { css }, language: "css/css", languageOptions: { tolerant: true } }).run(
  "no-hard-coded-colour in stylesheets",
  rule,
  {
    valid: [
      { filename: "src/a.css", code: "#root { color: var(--colour-text); background: transparent; }", options: options() },
      { filename: "src/a.css", code: ".a { color: #081020; }", options: options({ "src/a.css": { "#081020": 1 } }) },
    ],
    invalid: [
      {
        filename: "src/a.css",
        code: ".a { color: #FF00FF; border: 1px solid rgba(1, 2, 3, .5); outline-color: Red; }",
        options: options(),
        errors: [colour("#ff00ff"), colour("rgba(1,2,3,.5)"), colour("red")],
      },
    ],
  },
);
