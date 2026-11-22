// Shareable map state in the query string (docs/design/README.md, 4.2): `d` is the map date and `l` the
// visible layer, for example `?d=2026-02-21&l=swe`. Other parameters are left as they are.
export type UrlState = { date: string | null; layer: string | null };

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const LAYER_ID = /^[a-z][a-z0-9_]*$/;

export function readUrlState(search: string): UrlState {
  const params = new URLSearchParams(search);
  const date = params.get("d");
  const layer = params.get("l");
  return {
    date: date && isCalendarDate(date) ? date : null,
    layer: layer && LAYER_ID.test(layer) ? layer : null,
  };
}

// Date.parse rolls 2026-02-30 over to 2 March, so the date must survive a round trip.
function isCalendarDate(value: string) {
  if (!ISO_DATE.test(value)) return false;
  const time = Date.parse(`${value}T00:00:00Z`);
  return !Number.isNaN(time) && new Date(time).toISOString().slice(0, 10) === value;
}

export function writeUrlState(search: string, state: UrlState): string {
  const params = new URLSearchParams(search);
  for (const [key, value] of [
    ["d", state.date],
    ["l", state.layer],
  ] as const) {
    if (value) params.set(key, value);
    else params.delete(key);
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}
