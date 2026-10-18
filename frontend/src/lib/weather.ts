export const WEATHER_HORIZONS = [24, 48, 72, 120] as const;

export type WeatherHorizon = (typeof WEATHER_HORIZONS)[number];

export type WeatherVariable = "precipitation_total" | "snowfall";

export const WEATHER_VARIABLES: Array<{ id: WeatherVariable; label: string }> = [
  { id: "precipitation_total", label: "Precip" },
  { id: "snowfall", label: "Snow" },
];

type Asset = {
  path: string;
  bytes: number;
  sha256: string;
};

type WeatherField = {
  available: boolean;
  units?: string;
  basis?: string;
  reason?: string;
  asset?: Asset;
  visualization?: {
    asset: Asset;
    bounds: [number, number, number, number];
    scale_min_mm: number;
    scale_max_mm: number;
    region_max_mm: number;
  };
};

type WeatherHorizonData = {
  valid_at: string;
  precipitation_total: WeatherField;
  snowfall: WeatherField;
};

export type WeatherModel = {
  id: string;
  name: string;
  attribution: string;
  run_at: string;
  source: string;
  grid_degrees: number;
  horizons: Record<string, WeatherHorizonData>;
};

export type WeatherManifest = {
  schema_version: number;
  generated_at: string | null;
  common_horizons_hours: number[];
  models: WeatherModel[];
  unavailable_models?: Array<{ id: string; name: string; reason: string }>;
};

export type WeatherOverlay = {
  imageUrl: string;
  bounds: [number, number, number, number];
  scaleMaxMm: number;
  regionMaxMm: number;
  variable: WeatherVariable;
  modelName: string;
  attribution: string;
  gridDegrees: number;
  runAt: string;
  validAt: string;
};

export function weatherField(
  model: WeatherModel | undefined,
  horizon: number,
  variable: WeatherVariable,
): WeatherField | undefined {
  return model?.horizons[String(horizon)]?.[variable];
}

export function weatherOverlay(
  manifest: WeatherManifest | null,
  modelId: string | null,
  variable: WeatherVariable,
  horizon: WeatherHorizon | null,
  manifestUrl: string,
): WeatherOverlay | null {
  if (!manifest || horizon === null) return null;
  const model = manifest.models.find((item) => item.id === modelId);
  const visualization = weatherField(model, horizon, variable)?.visualization;
  if (!model || !visualization) return null;
  const baseUrl = new URL(manifestUrl, window.location.href);
  return {
    imageUrl: new URL(visualization.asset.path, baseUrl).toString(),
    bounds: visualization.bounds,
    scaleMaxMm: visualization.scale_max_mm,
    regionMaxMm: visualization.region_max_mm,
    variable,
    modelName: model.name,
    attribution: model.attribution,
    gridDegrees: model.grid_degrees,
    runAt: model.run_at,
    validAt: model.horizons[String(horizon)].valid_at,
  };
}
