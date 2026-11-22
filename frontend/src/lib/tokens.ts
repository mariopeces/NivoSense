// MapLibre paint properties and Recharts SVG attributes need resolved colour values, not var(): read them
// from the CSS variables that src/styles/tokens.css defines on :root.
export function token(name: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
  if (!value) throw new Error(`Missing design token --${name}`);
  return value;
}
