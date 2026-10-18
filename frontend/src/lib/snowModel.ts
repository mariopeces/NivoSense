export const SNOW_MODEL_SCHEMA_VERSION = 1;

export type SnowLayerId = "observed_snow_10m" | "swe" | "depth";

export const SNOW_LAYERS: Array<{ id: SnowLayerId; label: string; title: string }> = [
  { id: "observed_snow_10m", label: "S2 10 m", title: "Observed snow cover, Sentinel-2 at 10 m" },
  { id: "swe", label: "SWE", title: "Modelled snow water equivalent" },
  { id: "depth", label: "Depth", title: "Modelled snow depth" },
];

export type Quantiles = { p10: number; p50: number; p90: number };

export type SnowLayerInfo = {
  image: string;
  corners: [number, number][];
  date: string;
  units?: string;
  scale_max?: number;
  minimum_visible?: number;
  resolution_m?: number;
  valid_fraction?: number;
  snow_fraction_of_valid?: number;
  source?: string;
};

export type SnowModelBasin = {
  id: string;
  name: string;
  area_km2: number;
  series?: string;
  latest?: { date: string; swe_hm3: Quantiles; snow_area_km2: Quantiles };
};

export type SnowModelManifest = {
  schema_version: number;
  region: { id: string; name: string } | null;
  generated_at: string | null;
  hydrological_year: number | null;
  forcing?: { model: string; provider: string; start: string; last_day: string };
  model: {
    status: "available" | "unavailable";
    reasons: string[];
    resolution_m?: number;
    members?: number;
    calibration?: {
      created_at: string;
      years: number[];
      gate: { passed: boolean; reasons: string[] };
      metrics: {
        posterior: { f1: number; mcc: number; accuracy: number; cells: number };
        prior: { f1: number };
        test_dates_with_snow: number;
      };
    };
    limitations?: string[];
  };
  basins: SnowModelBasin[];
  layers: Partial<Record<SnowLayerId, SnowLayerInfo>>;
  monitoring: Array<{ date: string; f1: number; cells: number }>;
};

export type BasinVolumeSeries = {
  basin: string;
  dates: string[];
  swe_hm3: Record<keyof Quantiles, number[]>;
  snow_area_km2: Record<keyof Quantiles, number[]>;
  snowfall_hm3: Record<keyof Quantiles, number[]>;
  melt_hm3: Record<keyof Quantiles, number[]>;
  previous_season?: {
    year: number;
    dates: string[];
    swe_hm3: Record<keyof Quantiles, number[]>;
  };
};

export type SnowOverlay = {
  layer: SnowLayerId;
  imageUrl: string;
  corners: [number, number][];
  info: SnowLayerInfo;
};

export function snowOverlay(
  manifest: SnowModelManifest | null,
  layer: SnowLayerId | null,
  manifestUrl: string,
): SnowOverlay | null {
  const info = layer ? manifest?.layers[layer] : undefined;
  if (!layer || !info) return null;
  return {
    layer,
    imageUrl: new URL(info.image, new URL(manifestUrl, window.location.href)).toString(),
    corners: info.corners,
    info,
  };
}
