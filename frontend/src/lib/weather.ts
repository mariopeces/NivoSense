export const WEATHER_HORIZONS = [24, 48, 72, 120] as const;

export type WeatherHorizon = (typeof WEATHER_HORIZONS)[number];

type Asset = {
  path: string;
  bytes: number;
  sha256: string;
};

type WeatherHorizonData = {
  valid_at: string;
  precipitation_total: {
    available: boolean;
    units: string;
    asset: Asset;
    visualization: {
      asset: Asset;
      bounds: [number, number, number, number];
      scale_min_mm: number;
      scale_max_mm: number;
    };
  };
  snowfall: {
    available: boolean;
    reason?: string;
  };
};

export type WeatherManifest = {
  schema_version: number;
  generated_at: string | null;
  common_horizons_hours: number[];
  models: Array<{
    id: string;
    run_at: string;
    source: string;
    horizons: Record<string, WeatherHorizonData>;
  }>;
};

export type WeatherOverlay = {
  imageUrl: string;
  bounds: [number, number, number, number];
  scaleMaxMm: number;
};

export function weatherOverlay(
  manifest: WeatherManifest | null,
  horizon: WeatherHorizon | null,
  manifestUrl: string,
): WeatherOverlay | null {
  if (!manifest || horizon === null) return null;
  const model = manifest.models.find((item) => item.id === "gfs");
  const visualization = model?.horizons[String(horizon)]?.precipitation_total.visualization;
  if (!visualization) return null;
  const baseUrl = new URL(manifestUrl, window.location.href);
  return {
    imageUrl: new URL(visualization.asset.path, baseUrl).toString(),
    bounds: visualization.bounds,
    scaleMaxMm: visualization.scale_max_mm,
  };
}
