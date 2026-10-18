import type { ObservationScene } from "./types";

type StaticObservationManifest = {
  observation: { date: string };
  coverage: { bbox: [number, number, number, number] };
  web_layer: { path: string };
};

export function staticObservationScene(
  payload: unknown,
  manifestUrl: string,
): ObservationScene {
  if (!isManifest(payload)) {
    throw new Error("Invalid static snow observation manifest");
  }
  return {
    date: payload.observation.date,
    image_url: new URL(payload.web_layer.path, manifestUrl).toString(),
    image_bbox: payload.coverage.bbox,
  };
}

function isManifest(value: unknown): value is StaticObservationManifest {
  if (!value || typeof value !== "object") return false;
  const manifest = value as Record<string, unknown>;
  if (!manifest.observation || typeof manifest.observation !== "object") return false;
  if (!manifest.coverage || typeof manifest.coverage !== "object") return false;
  if (!manifest.web_layer || typeof manifest.web_layer !== "object") return false;

  const observation = manifest.observation as Record<string, unknown>;
  const coverage = manifest.coverage as Record<string, unknown>;
  const webLayer = manifest.web_layer as Record<string, unknown>;
  const bbox = coverage.bbox;
  return (
    typeof observation.date === "string" &&
    /^\d{4}-\d{2}-\d{2}$/.test(observation.date) &&
    typeof webLayer.path === "string" &&
    webLayer.path.length > 0 &&
    Array.isArray(bbox) &&
    bbox.length === 4 &&
    bbox.every((coordinate) => typeof coordinate === "number") &&
    bbox[0] < bbox[2] &&
    bbox[1] < bbox[3]
  );
}
