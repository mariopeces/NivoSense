/** @type {import('tailwindcss').Config} */
import tokens from "../docs/design/tokens.json" with { type: "json" };

// Every theme value points at a CSS variable from src/styles/tokens.css (generated from tokens.json),
// so the theme holds names only and no value of its own.
const names = (group) =>
  Object.fromEntries(
    Object.keys(group)
      .filter((key) => !key.startsWith("$"))
      .map((key) => [key, key]),
  );
const vars = (group, prefix) =>
  Object.fromEntries(Object.keys(names(group)).map((key) => [key, `var(--${prefix}-${key})`]));

const fontSize = Object.fromEntries(
  Object.keys(names(tokens.type)).map((key) => [
    key,
    [
      `var(--type-${key}-size)`,
      { lineHeight: `var(--type-${key}-lh)`, fontWeight: `var(--type-${key}-weight)` },
    ],
  ]),
);

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    // Replaces Tailwind's default palette: only token colours can be used in class names.
    colors: { transparent: "transparent", current: "currentColor", inherit: "inherit", ...vars(tokens.color, "color") },
    extend: {
      fontFamily: vars(tokens.font.family, "font-family"),
      fontWeight: vars(tokens.font.weight, "font-weight"),
      fontSize,
      spacing: {
        ...vars(tokens.space, "space"),
        rail: "var(--layout-rail-width)",
        "rail-button": "var(--layout-rail-button)",
        panel: "var(--layout-panel-width)",
        "map-control": "var(--layout-map-control)",
        tabbar: "var(--layout-tabbar-height)",
        "sheet-peek": "var(--layout-sheet-peek)",
        "sheet-half": "var(--layout-sheet-half)",
        touch: "var(--layout-touch-target)",
      },
      borderRadius: vars(tokens.radius, "radius"),
      boxShadow: vars(tokens.shadow, "shadow"),
      transitionDuration: vars(tokens.motion.duration, "motion-duration"),
      transitionTimingFunction: vars(tokens.motion.easing, "motion-easing"),
      zIndex: vars(tokens.z, "z"),
    },
  },
  plugins: [],
};
