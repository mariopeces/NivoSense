import css from "@eslint/css";
import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";
import baseline from "./colour-baseline.json" with { type: "json" };
import noHardCodedColour from "./eslint/no-hard-coded-colour.js";

const TOKENS_FILE = "src/styles/tokens.css";
const SCRIPTS = "{js,jsx,mjs,cjs,ts,tsx,mts,cts}";
// The rule's own tests hold the colours they feed it.
const RULE_TESTS = "eslint/**/*.test.*";
const local = { rules: { "no-hard-coded-colour": noHardCodedColour } };
const colourRule = (options = {}) => ({
  "local/no-hard-coded-colour": ["error", { tokensFile: TOKENS_FILE, baseline, ...options }],
});

export default tseslint.config(
  { ignores: ["dist"] },
  // Inline configuration is off, so no comment can switch a rule off (a block `/* eslint-disable */` would hide
  // colours); the colour rule also reports any such comment as an error. Change this file instead.
  { linterOptions: { noInlineConfig: true, reportUnusedDisableDirectives: "error" } },
  {
    files: [`src/**/*.${SCRIPTS}`, `*.${SCRIPTS}`, `eslint/**/*.${SCRIPTS}`],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { globals: globals.browser },
    plugins: { "react-hooks": reactHooks, local },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      ...colourRule(),
    },
  },
  {
    files: [`*.${SCRIPTS}`, `eslint/**/*.${SCRIPTS}`],
    languageOptions: { globals: globals.node },
  },
  {
    // The Tailwind theme maps the tokens; it must not name colours of its own, even outside colour keys.
    files: ["tailwind.config.js"],
    rules: colourRule({ namedColoursAnywhere: true }),
  },
  {
    files: [RULE_TESTS],
    rules: { "local/no-hard-coded-colour": "off" },
  },
  {
    files: ["src/**/*.css"],
    ignores: [TOKENS_FILE],
    language: "css/css",
    // Tailwind's @tailwind and @apply at-rules are not standard CSS.
    languageOptions: { tolerant: true },
    plugins: { css, local },
    rules: colourRule(),
  },
);
