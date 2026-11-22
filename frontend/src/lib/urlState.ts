// Shareable map state in the query string (docs/design/README.md, 4.2): `d` is the map date and `l` the
// visible layers with their opacity in percent, for example `?d=2026-02-21&l=rgb:100,snow_obs:80`. A layer
// without an opacity is at 100. Other parameters are left as they are.
export type VisibleLayers = Array<{ id: string; opacity: number }>;
export type UrlState = { date: string | null; layers: VisibleLayers };

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const LAYER = /^([a-z][a-z0-9_]*)(?::(\d{1,3}))?$/;

// Date.parse rolls 2026-02-30 over to 2 March, so the date must survive a round trip.
function isCalendarDate(value: string) {
  if (!ISO_DATE.test(value)) return false;
  const time = Date.parse(`${value}T00:00:00Z`);
  return !Number.isNaN(time) && new Date(time).toISOString().slice(0, 10) === value;
}

export function readUrlState(search: string): UrlState {
  const params = new URLSearchParams(search);
  const date = params.get("d");
  const layers: VisibleLayers = [];
  for (const part of (params.get("l") ?? "").split(",")) {
    const match = LAYER.exec(part);
    if (!match || layers.some((layer) => layer.id === match[1])) continue;
    const opacity = match[2] === undefined ? 100 : Number(match[2]);
    if (opacity <= 100) layers.push({ id: match[1], opacity });
  }
  return { date: date && isCalendarDate(date) ? date : null, layers };
}

export function writeUrlState(search: string, state: UrlState): string {
  const params = new URLSearchParams(search);
  if (state.date) params.set("d", state.date);
  else params.delete("d");
  if (state.layers.length) params.set("l", state.layers.map((layer) => `${layer.id}:${layer.opacity}`).join(","));
  else params.delete("l");
  // URLSearchParams escapes the separators; they are safe in a query string and keep shared links readable.
  const query = params.toString().replace(/%2C/g, ",").replace(/%3A/g, ":");
  return query ? `?${query}` : "";
}
