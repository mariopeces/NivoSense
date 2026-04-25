import { useEffect, useRef, useState } from "react";
import maplibregl, { type StyleSpecification } from "maplibre-gl";
import BasemapSwitcher, { type BasemapId } from "./BasemapSwitcher";
import { bboxOfGeometry } from "../lib/geo";

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

type FC = {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    properties: { cod_uni: number; [k: string]: unknown };
    geometry: { type: string; coordinates: unknown };
  }>;
};

type Props = {
  basinsFC: FC | null;
  selectedBasinId: string | null;
  onBasinSelect: (id: string | null) => void;
};

export default function Map({
  basinsFC,
  selectedBasinId,
  onBasinSelect,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const basinsFCRef = useRef<FC | null>(null);
  const selectedRef = useRef<string | null>(null);
  const onBasinSelectRef = useRef(onBasinSelect);
  const isFirstBasemapRun = useRef(true);
  const [basemap, setBasemap] = useState<BasemapId>("dark");

  useEffect(() => {
    basinsFCRef.current = basinsFC;
  }, [basinsFC]);

  useEffect(() => {
    selectedRef.current = selectedBasinId;
  }, [selectedBasinId]);

  useEffect(() => {
    onBasinSelectRef.current = onBasinSelect;
  }, [onBasinSelect]);

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

    map.on("style.load", () => {
      (map as unknown as { __basinClickAttached?: boolean }).__basinClickAttached =
        false;
      addBasinsLayers(map, basinsFCRef.current);
      applySelected(map, selectedRef.current);
      attachBasinInteractions(map, onBasinSelectRef);
    });

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (isFirstBasemapRun.current) {
      isFirstBasemapRun.current = false;
      return;
    }
    map.setStyle(BASEMAPS[basemap]);
  }, [basemap]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !basinsFC) return;
    if (map.isStyleLoaded()) {
      addBasinsLayers(map, basinsFC);
      applySelected(map, selectedBasinId);
      attachBasinInteractions(map, onBasinSelectRef);
    }
  }, [basinsFC]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !basinsFC) return;

    const apply = () => {
      applySelected(map, selectedBasinId);

      if (selectedBasinId) {
        const feature = basinsFC.features.find(
          (f) => String(f.properties.cod_uni) === selectedBasinId,
        );
        if (feature) {
          map.fitBounds(bboxOfGeometry(feature.geometry), {
            padding: 80,
            duration: 800,
          });
        }
      } else {
        map.fitBounds(SIERRA_NEVADA_BOUNDS, {
          padding: 60,
          duration: 600,
        });
      }
    };

    if (map.isStyleLoaded() && map.getLayer("basins-fill")) {
      apply();
    } else {
      map.once("idle", apply);
    }
  }, [selectedBasinId, basinsFC]);

  return (
    <>
      <div ref={containerRef} className="absolute inset-0" />
      <BasemapSwitcher value={basemap} onChange={setBasemap} />
    </>
  );
}

function addBasinsLayers(map: maplibregl.Map, fc: FC | null) {
  if (!fc) return;
  if (map.getSource("basins")) return;

  map.addSource("basins", {
    type: "geojson",
    data: fc as unknown as GeoJSON.FeatureCollection,
  });

  map.addLayer({
    id: "basins-fill",
    type: "fill",
    source: "basins",
    paint: {
      "fill-color": "#67e8f9",
      "fill-opacity": 0.08,
    },
  });

  map.addLayer({
    id: "basins-line",
    type: "line",
    source: "basins",
    paint: {
      "line-color": "rgba(103, 232, 249, 0.55)",
      "line-width": 1.4,
    },
  });

  map.addLayer({
    id: "basins-fill-selected",
    type: "fill",
    source: "basins",
    filter: ["==", ["get", "cod_uni"], -1],
    paint: {
      "fill-color": "#22d3ee",
      "fill-opacity": 0.22,
    },
  });

  map.addLayer({
    id: "basins-line-selected",
    type: "line",
    source: "basins",
    filter: ["==", ["get", "cod_uni"], -1],
    paint: {
      "line-color": "#67e8f9",
      "line-width": 3,
      "line-blur": 0.5,
    },
  });
}

function applySelected(map: maplibregl.Map, selectedId: string | null) {
  if (!map.getLayer("basins-fill-selected")) return;
  const codUni = selectedId ? Number(selectedId) : -1;
  map.setFilter("basins-fill-selected", ["==", ["get", "cod_uni"], codUni]);
  map.setFilter("basins-line-selected", ["==", ["get", "cod_uni"], codUni]);
}

function attachBasinInteractions(
  map: maplibregl.Map,
  onSelectRef: { current: (id: string | null) => void },
) {
  if (!map.getLayer("basins-fill")) return;
  if ((map as unknown as { __basinClickAttached?: boolean }).__basinClickAttached)
    return;
  (map as unknown as { __basinClickAttached?: boolean }).__basinClickAttached =
    true;

  map.on("click", "basins-fill", (e) => {
    const feature = e.features?.[0];
    if (!feature) return;
    const codUni = feature.properties?.cod_uni;
    if (codUni == null) return;
    onSelectRef.current(String(codUni));
  });

  map.on("mouseenter", "basins-fill", () => {
    map.getCanvas().style.cursor = "pointer";
  });
  map.on("mouseleave", "basins-fill", () => {
    map.getCanvas().style.cursor = "";
  });
}
