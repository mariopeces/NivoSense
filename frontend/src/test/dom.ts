// Shared setup for component tests running under jsdom (each file opts in with `@vitest-environment jsdom`).
import { readFileSync } from "node:fs";
import path from "node:path";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
import { TOKENS_JSON, flattenTokens } from "../../scripts/build-tokens.mjs";

// jsdom does not load src/styles/tokens.css, and token() reads computed CSS variables: set them inline.
for (const [name, value] of flattenTokens(JSON.parse(readFileSync(TOKENS_JSON, "utf8")))) {
  document.documentElement.style.setProperty(`--${name}`, value);
}

let mobile = false;
/** Switch the (max-width: 767px) media query the shell uses to pick the mobile layout. */
export function setMobile(value: boolean) {
  mobile = value;
}
window.matchMedia = ((query: string) => ({
  matches: query.includes("max-width") ? mobile : false,
  media: query,
  onchange: null,
  addEventListener: () => {},
  removeEventListener: () => {},
  addListener: () => {},
  removeListener: () => {},
  dispatchEvent: () => false,
})) as typeof window.matchMedia;

afterEach(() => {
  cleanup();
  mobile = false;
});

/** Real repo files, so component tests run on the data the site serves rather than invented values. */
export function repoFile(relative: string): string {
  return readFileSync(path.resolve(__dirname, "../../..", relative), "utf8");
}
