import type { LngLatBoundsLike } from "maplibre-gl";

type AnyGeometry = {
  type: string;
  coordinates: unknown;
};

export function bboxOfGeometry(geometry: AnyGeometry): LngLatBoundsLike {
  let minLng = Infinity;
  let minLat = Infinity;
  let maxLng = -Infinity;
  let maxLat = -Infinity;

  const walk = (node: unknown): void => {
    if (
      Array.isArray(node) &&
      typeof node[0] === "number" &&
      typeof node[1] === "number"
    ) {
      const lng = node[0] as number;
      const lat = node[1] as number;
      if (lng < minLng) minLng = lng;
      if (lng > maxLng) maxLng = lng;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
      return;
    }
    if (Array.isArray(node)) {
      node.forEach(walk);
    }
  };

  walk(geometry.coordinates);
  return [
    [minLng, minLat],
    [maxLng, maxLat],
  ];
}

// The source names are upper case without accents; this restores the official spelling of the words that
// carry one (Cádiar, as in the Nomenclátor Geográfico de Andalucía).
const ACCENTED: Record<string, string> = { cadiar: "cádiar" };

export function prettifyBasinName(raw: string): string {
  return raw
    .toLowerCase()
    .replace(/[a-z]+/g, (word) => ACCENTED[word] ?? word)
    .replace(/\brio\b/g, "Río")
    .replace(/(^|\s)([a-záéíóúñ])/g, (_, prefix, ch) => prefix + ch.toUpperCase())
    .replace(/\bO\b/g, "o");
}
