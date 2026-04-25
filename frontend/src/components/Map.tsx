import { useEffect, useRef, useState } from "react";
import maplibregl, { type StyleSpecification } from "maplibre-gl";
import BasemapSwitcher, { type BasemapId } from "./BasemapSwitcher";

const SIERRA_NEVADA_BOUNDS: [[number, number], [number, number]] = [
  [-3.55, 36.92],
  [-2.95, 37.18],
];

const BASEMAPS: Record<BasemapId, StyleSpecification> = {
  dark: {
    version: 8,
    sources: {
      carto: {
        type: "raster",
        tiles: [
          "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
          "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
          "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        ],
        tileSize: 256,
        attribution: "© OpenStreetMap · © CARTO",
      },
    },
    layers: [{ id: "carto", type: "raster", source: "carto" }],
  },
  light: {
    version: 8,
    sources: {
      carto: {
        type: "raster",
        tiles: [
          "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
          "https://b.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
          "https://c.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
        ],
        tileSize: 256,
        attribution: "© OpenStreetMap · © CARTO",
      },
    },
    layers: [{ id: "carto", type: "raster", source: "carto" }],
  },
  satellite: {
    version: 8,
    sources: {
      imagery: {
        type: "raster",
        tiles: [
          "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        ],
        tileSize: 256,
        attribution: "© Esri · Maxar · Earthstar Geographics",
      },
    },
    layers: [{ id: "imagery", type: "raster", source: "imagery" }],
  },
};

export default function Map() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [basemap, setBasemap] = useState<BasemapId>("dark");

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: BASEMAPS.dark,
      bounds: SIERRA_NEVADA_BOUNDS,
      fitBoundsOptions: { padding: 60 },
      attributionControl: { compact: true },
    });

    map.addControl(new maplibregl.NavigationControl(), "top-right");
    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.setStyle(BASEMAPS[basemap]);
  }, [basemap]);

  return (
    <>
      <div ref={containerRef} className="absolute inset-0" />
      <BasemapSwitcher value={basemap} onChange={setBasemap} />
    </>
  );
}
