import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

// Colours live in the tokens file; everywhere else they are referenced through CSS variables or Tailwind theme names.
// esquery drops backslashes inside selector regexes, so the pattern uses character classes instead of \b and \(.
const TOKENS_FILE = "src/styles/tokens.css";
const COLOUR = "/#[0-9a-fA-F]{3,8}([^0-9a-zA-Z_]|$)|(rgb|hsl)a?[(]/";
const COLOUR_MESSAGE = `Hard-coded colour: define it in ${TOKENS_FILE} and use the token.`;

export default tseslint.config(
  { ignores: ["dist"] },
  {
    files: ["src/**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { globals: globals.browser },
    plugins: { "react-hooks": reactHooks },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      "no-restricted-syntax": [
        "error",
        { selector: `Literal[value=${COLOUR}]`, message: COLOUR_MESSAGE },
        { selector: `TemplateElement[value.raw=${COLOUR}]`, message: COLOUR_MESSAGE },
      ],
    },
  },
);
