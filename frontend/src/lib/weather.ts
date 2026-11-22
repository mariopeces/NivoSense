import palettes from "../../../pipelines/weather_forecasts/palettes.json";
import { numero } from "./format";

export const WEATHER_SCHEMA_VERSION = 2;

export const WEATHER_HORIZONS = [24, 48, 72, 120] as const;

export type WeatherHorizon = (typeof WEATHER_HORIZONS)[number];

export type WeatherVariable = "precipitation_total" | "temperature_2m" | "wind_speed_10m";

/** Order of preference when a default has to be picked: precipitation first, then the always-present fields. */
export const WEATHER_VARIABLES: WeatherVariable[] = ["precipitation_total", "temperature_2m", "wind_speed_10m"];

type Asset = {
  path: string;
  bytes: number;
  sha256: string;
};

type WeatherField = {
  available: boolean;
  units?: string;
  reason?: string;
  note?: string;
  asset?: Asset;
  visualization?: {
    asset: Asset;
    bounds: [number, number, number, number];
    scale_min: number;
    scale_max: number;
    region_min: number;
    region_max: number;
  };
};

type WeatherHorizonData = { valid_at: string } & Record<WeatherVariable, WeatherField>;

export type WeatherModel = {
  id: string;
  name: string;
  attribution: string;
  run_at: string;
  source: string;
  grid_degrees: number;
  resolution_km: number;
  experimental?: boolean;
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
  scaleMin: number;
  scaleMax: number;
  regionMin: number;
  regionMax: number;
  units: string;
  variable: WeatherVariable;
  /** Accumulated precipitation that is zero over the whole region: the image is fully transparent. */
  dry: boolean;
  modelName: string;
  attribution: string;
  resolution: string;
  experimental: boolean;
  runAt: string;
  validAt: string;
  note: string | null;
};

/** "0,025° (~2,5 km)": the grid in degrees and the native resolution the model is known by. */
export function resolutionLabel(model: Pick<WeatherModel, "grid_degrees" | "resolution_km">): string {
  const degrees = numero(model.grid_degrees, model.grid_degrees < 0.1 ? 3 : 2);
  const km = numero(model.resolution_km, model.resolution_km < 10 ? 1 : 0);
  return `${degrees}° (~${km} km)`;
}

export function weatherField(
  model: WeatherModel | undefined,
  horizon: number,
  variable: WeatherVariable,
): WeatherField | undefined {
  return model?.horizons[String(horizon)]?.[variable];
}

/** Precipitation that nowhere reaches the lowest value the map paints. Temperature and wind are never dry. */
export function isDry(variable: WeatherVariable, field: WeatherField | undefined): boolean {
  const visualization = field?.visualization;
  return variable === "precipitation_total" && !!visualization && visualization.region_max < palettes.min_visible_mm;
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
  const field = weatherField(model, horizon, variable);
  const visualization = field?.visualization;
  if (!model || !visualization) return null;
  const baseUrl = new URL(manifestUrl, window.location.href);
  return {
    imageUrl: new URL(visualization.asset.path, baseUrl).toString(),
    bounds: visualization.bounds,
    scaleMin: visualization.scale_min,
    scaleMax: visualization.scale_max,
    regionMin: visualization.region_min,
    regionMax: visualization.region_max,
    units: field?.units ?? "",
    variable,
    dry: isDry(variable, field),
    modelName: model.name,
    attribution: model.attribution,
    resolution: resolutionLabel(model),
    experimental: model.experimental === true,
    runAt: model.run_at,
    validAt: model.horizons[String(horizon)].valid_at,
    note: field?.note ?? null,
  };
}

/** Keeps a horizon only if the model offers it for the variable; otherwise the shortest one it does offer. */
export function resolveHorizon(
  model: WeatherModel | undefined,
  variable: WeatherVariable,
  horizon: WeatherHorizon | null,
): WeatherHorizon | null {
  if (horizon !== null && weatherField(model, horizon, variable)?.available) return horizon;
  return WEATHER_HORIZONS.find((item) => weatherField(model, item, variable)?.available) ?? null;
}

/**
 * What to show when the tab opens: the shortest horizon that has something to see (precipitation if it is not
 * dry, else temperature, else wind), so a dry day never opens on a transparent map. Falls back to the first
 * available field, dry or not.
 */
export function defaultSelection(
  model: WeatherModel | undefined,
): { variable: WeatherVariable; horizon: WeatherHorizon } | null {
  let fallback: { variable: WeatherVariable; horizon: WeatherHorizon } | null = null;
  for (const horizon of WEATHER_HORIZONS) {
    for (const variable of WEATHER_VARIABLES) {
      const field = weatherField(model, horizon, variable);
      if (!field?.available) continue;
      if (!isDry(variable, field)) return { variable, horizon };
      fallback ??= { variable, horizon };
    }
  }
  return fallback;
}
