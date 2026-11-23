import type { CatalogEntry } from "./catalog";

export type Range = { p10: number; p50: number; p90: number };
export type SnowRanges = { area: Range; meanDepth: Range; peakDepth: Range };

const QUANTILES = ["p10", "p50", "p90"] as const;

function range(scores: Record<string, number>, prefix: string, factor = 1): Range | null {
  const values = QUANTILES.map((q) => scores[`${prefix}_${q}`]);
  if (values.some((value) => typeof value !== "number" || !Number.isFinite(value))) return null;
  return { p10: values[0] * factor, p50: values[1] * factor, p90: values[2] * factor };
}

/**
 * The ensemble summary a snow_depth entry carries in its qa scores (pipelines/snow_model_v2/daily.py): snow
 * covered area in km2 and depth in cm, as p10, p50 and p90 over the members. `group` is `domain` or
 * `basin_<cod_uni>`. Null when the entry has no summary for the group.
 */
export function snowRanges(entry: CatalogEntry | null | undefined, group: string): SnowRanges | null {
  const scores = entry?.qa?.scores;
  if (!scores) return null;
  const area = range(scores, `${group}_snow_area_km2`);
  const meanDepth = range(scores, `${group}_depth_mean_m`, 100);
  const peakDepth = range(scores, `${group}_depth_peak_m`, 100);
  return area && meanDepth && peakDepth ? { area, meanDepth, peakDepth } : null;
}
