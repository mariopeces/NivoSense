import css from "@eslint/css";
import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";
import baseline from "./colour-baseline.json" with { type: "json" };
import noHardCodedColour from "./eslint/no-hard-coded-colour.js";

const TOKENS_FILE = "src/styles/tokens.css";
const local = { rules: { "no-hard-coded-colour": noHardCodedColour } };
const colourRule = { "local/no-hard-coded-colour": ["error", { tokensFile: TOKENS_FILE, baseline }] };

export default tseslint.config(
  { ignores: ["dist"] },
  {
    files: ["src/**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { globals: globals.browser },
    plugins: { "react-hooks": reactHooks, local },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      ...colourRule,
    },
  },
  {
    // The Tailwind theme maps the tokens; it must not define colours of its own.
    files: ["tailwind.config.js"],
    plugins: { local },
    rules: colourRule,
  },
  {
    files: ["src/**/*.css"],
    ignores: [TOKENS_FILE],
    language: "css/css",
    // Tailwind's @tailwind and @apply at-rules are not standard CSS.
    languageOptions: { tolerant: true },
    plugins: { css, local },
    rules: colourRule,
  },
);
