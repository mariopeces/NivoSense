import rampsFile from "../../../docs/design/ramps.json";
import type { CatalogEntry, CatalogIndex } from "./catalog";

// The map ramps the pipelines colour their display rasters with (pipelines/ramps.py reads the same file),
// so a legend drawn from them shows exactly what the image shows.
export type RampClass = {
  min?: number;
  max?: number | null;
  key?: string;
  alpha: number;
  label_es: string;
  color: string | null;
  pattern?: {
    kind: "dots" | "hatch";
    color: string;
    alpha?: number;
    spacing_px: number;
    radius_px?: number;
    width_px?: number;
  };
};
export type Ramp = {
  label_es: string;
  unit: string | null;
  categorical?: boolean;
  transparent_below?: number | null;
  classes: RampClass[];
};
export const RAMPS = (rampsFile as unknown as { layers: Record<string, Ramp> }).layers;

export type LayerGroup = "nieve" | "imagen";
export type LayerSpec = { id: string; copy: string; ramp: string | null; group: LayerGroup };

// Every layer of pipelines/catalog/layers.py, in the order of the spec's Nieve panel, with its copy deck key
// and its ramp (the same pairs as RAMP_OF_LAYER in pipelines/ramps.py; tests/test_ramps.py keeps them equal).
// A layer the catalogue lists that is not here still gets a row (see layerSpecs).
export const LAYER_SPECS: LayerSpec[] = [
  { id: "snow_obs", copy: "nieve_observada", ramp: "snow_cover_observed", group: "nieve" },
  { id: "snow_gapfill", copy: "nieve_diaria", ramp: "snow_cover_probability", group: "nieve" },
  { id: "swe", copy: "swe", ramp: "swe", group: "nieve" },
  { id: "snow_depth", copy: "espesor", ramp: "snow_depth", group: "nieve" },
  { id: "rgb", copy: "color_real", ramp: null, group: "imagen" },
];

// Layers the site does not offer: shown locked whatever the catalogue holds, and their entries are never listed,
// drawn or counted on the timeline. SWE: no field measurement exists to validate it (docs/snow-evaluation.md), and
// catalogues still hold the v1 entries.
export const LOCKED_LAYERS = new Set(["swe"]);

export const isLocked = (id: string) => LOCKED_LAYERS.has(id);

/** The entries of a layer the site offers: none for a locked layer. */
export function entriesOf(index: CatalogIndex | null, id: string): CatalogEntry[] {
  return isLocked(id) ? [] : (index?.layers[id]?.entries ?? []);
}

/** Layers with a product for every day (the model and its gap fill): a day without an entry has no data. */
const DAILY_STATUSES = new Set(["modelled", "gapfilled"]);
export const isDaily = (entry: CatalogEntry) => DAILY_STATUSES.has(entry.status);

/** The known layers plus any other layer the catalogue lists, so every catalogued layer is reachable. */
export function layerSpecs(index: CatalogIndex | null): LayerSpec[] {
  const known = new Set(LAYER_SPECS.map((spec) => spec.id));
  const extra = Object.keys(index?.layers ?? {})
    .filter((id) => !known.has(id))
    .sort()
    .map((id): LayerSpec => ({ id, copy: "", ramp: null, group: "nieve" }));
  return [...LAYER_SPECS, ...extra];
}

const DAY_MS = 86_400_000;

/**
 * The entry a layer shows on a date: the one of that day, otherwise the nearest one (the earlier on a tie,
 * since a past scene is real and a later one may be a forecast). Daily layers (modelled and gap-filled) only show
 * their own day.
 * Null when the layer has no entry.
 */
export function entryFor(entries: CatalogEntry[], date: string): { entry: CatalogEntry; exact: boolean } | null {
  let best: CatalogEntry | null = null;
  let bestGap = Infinity;
  const target = Date.parse(`${date}T00:00:00Z`);
  // The model and the gap fill publish every day, so a day without an entry is outside their record: showing the
  // nearest day would draw snow of another date.
  const candidates = entries.filter((entry) => !isDaily(entry) || entry.date === date);
  for (const entry of candidates) {
    const gap = Math.abs(Date.parse(`${entry.date}T00:00:00Z`) - target) / DAY_MS;
    if (gap < bestGap || (gap === bestGap && best && entry.date < best.date)) {
      best = entry;
      bestGap = gap;
    }
  }
  return best ? { entry: best, exact: bestGap === 0 } : null;
}

/** The catalogue root: entry keys are relative to the folder that holds catalog/index.json. */
export function catalogRoot(indexUrl: string): string {
  return new URL("../", new URL(indexUrl, window.location.href)).toString();
}

export function pmtilesUrl(root: string, entry: CatalogEntry): string {
  return `pmtiles://${new URL(entry.pmtiles, root).toString()}`;
}

/** Class bounds of a stepped ramp for its legend labels: every min, then the last max if it is closed. */
export function rampBounds(ramp: Ramp): number[] {
  const bounds = ramp.classes.map((cls) => cls.min ?? 0);
  const last = ramp.classes[ramp.classes.length - 1].max;
  return last == null ? bounds : [...bounds, last];
}
