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

export function prettifyBasinName(raw: string): string {
  return raw
    .toLowerCase()
    .replace(/\brio\b/g, "Río")
    .replace(/(^|\s)([a-záéíóúñ])/g, (_, prefix, ch) => prefix + ch.toUpperCase())
    .replace(/\bO\b/g, "o");
}
