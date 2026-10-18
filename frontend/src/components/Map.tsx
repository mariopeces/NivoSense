import { useEffect, useRef } from "react";
import maplibregl, { type StyleSpecification } from "maplibre-gl";
import { bboxOfGeometry } from "../lib/geo";
import type { Webcam } from "../lib/types";

const SIERRA_NEVADA_BOUNDS: [[number, number], [number, number]] = [
  [-3.55, 36.92],
  [-2.95, 37.18],
];

const SATELLITE_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    imagery: {
      type: "raster",
      tiles: [
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      ],
      tileSize: 256,
      attribution: "Esri / Maxar / Earthstar Geographics",
    },
    "esri-labels": {
      type: "raster",
      tiles: [
        "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
      ],
      tileSize: 256,
      attribution: "Esri",
    },
  },
  layers: [
    { id: "imagery", type: "raster", source: "imagery" },
    { id: "labels", type: "raster", source: "esri-labels" },
  ],
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
  ndsiTileUrl: string | null;
  onBasinSelect: (id: string | null) => void;
  webcams: Webcam[];
  selectedWebcamId: string | null;
  onWebcamSelect: (id: string | null) => void;
};

export default function Map({
  basinsFC,
  selectedBasinId,
  ndsiTileUrl,
  onBasinSelect,
  webcams,
  selectedWebcamId,
  onWebcamSelect,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const basinsFCRef = useRef<FC | null>(null);
  const selectedRef = useRef<string | null>(null);
  const ndsiTileUrlRef = useRef<string | null>(null);
  const onBasinSelectRef = useRef(onBasinSelect);
  const webcamsRef = useRef<Webcam[]>([]);
  const selectedWebcamRef = useRef<string | null>(null);
  const onWebcamSelectRef = useRef(onWebcamSelect);

  useEffect(() => {
    basinsFCRef.current = basinsFC;
  }, [basinsFC]);

  useEffect(() => {
    selectedRef.current = selectedBasinId;
  }, [selectedBasinId]);

  useEffect(() => {
    ndsiTileUrlRef.current = ndsiTileUrl;
  }, [ndsiTileUrl]);

  useEffect(() => {
    onBasinSelectRef.current = onBasinSelect;
  }, [onBasinSelect]);

  useEffect(() => {
    webcamsRef.current = webcams;
  }, [webcams]);

  useEffect(() => {
    selectedWebcamRef.current = selectedWebcamId;
  }, [selectedWebcamId]);

  useEffect(() => {
    onWebcamSelectRef.current = onWebcamSelect;
  }, [onWebcamSelect]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: SATELLITE_STYLE,
      bounds: SIERRA_NEVADA_BOUNDS,
      fitBoundsOptions: { padding: 60 },
      attributionControl: { compact: true },
    });

    map.addControl(new maplibregl.NavigationControl(), "top-right");

    const setupLayers = () => {
      setNdsiLayer(map, ndsiTileUrlRef.current);
      if (basinsFCRef.current) {
        addBasinsLayers(map, basinsFCRef.current);
        applySelected(map, selectedRef.current);
        attachBasinInteractions(map, onBasinSelectRef);
      }
      addWebcamLayers(map, webcamsRef.current);
      applySelectedWebcam(map, selectedWebcamRef.current);
      attachWebcamInteractions(map, onWebcamSelectRef);
    };

    map.on("load", setupLayers);
    map.on("style.load", setupLayers);

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !basinsFC) return;
    if (!map.isStyleLoaded()) return;
    addBasinsLayers(map, basinsFC);
    applySelected(map, selectedBasinId);
    attachBasinInteractions(map, onBasinSelectRef);
  }, [basinsFC]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    setNdsiLayer(map, ndsiTileUrl);
    if (basinsFC) {
      addBasinsLayers(map, basinsFC);
      applySelected(map, selectedBasinId);
    }
  }, [ndsiTileUrl, basinsFC, selectedBasinId]);

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

    if (map.getLayer("basins-fill-selected")) {
      apply();
    } else {
      map.once("idle", apply);
    }
  }, [selectedBasinId, basinsFC]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    addWebcamLayers(map, webcams);
    applySelectedWebcam(map, selectedWebcamId);
    attachWebcamInteractions(map, onWebcamSelectRef);
  }, [webcams, selectedWebcamId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !selectedWebcamId) return;
    const webcam = webcams.find((item) => item.id === selectedWebcamId);
    if (!webcam) return;

    const focus = () => {
      applySelectedWebcam(map, selectedWebcamId);
      map.flyTo({
        center: [webcam.longitude, webcam.latitude],
        zoom: Math.max(map.getZoom(), 13),
        duration: 800,
      });
    };

    if (map.getLayer("webcams-selected")) focus();
    else map.once("idle", focus);
  }, [selectedWebcamId, webcams]);

  return <div ref={containerRef} className="absolute inset-0" />;
}

function webcamFeatureCollection(webcams: Webcam[]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: webcams.map((webcam) => ({
      type: "Feature",
      geometry: {
        type: "Point",
        coordinates: [webcam.longitude, webcam.latitude],
      },
      properties: {
        id: webcam.id,
        name: webcam.name,
      },
    })),
  };
}

function addWebcamLayers(map: maplibregl.Map, webcams: Webcam[]) {
  const data = webcamFeatureCollection(webcams);
  const source = map.getSource("webcams");
  if (source) {
    (source as maplibregl.GeoJSONSource).setData(data);
  } else {
    map.addSource("webcams", { type: "geojson", data });
  }

  if (!map.getLayer("webcams")) {
    map.addLayer({
      id: "webcams",
      type: "circle",
      source: "webcams",
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 5, 14, 8],
        "circle-color": "#0f172a",
        "circle-stroke-color": "#67e8f9",
        "circle-stroke-width": 2,
      },
    });
  }

  if (!map.getLayer("webcams-selected")) {
    map.addLayer({
      id: "webcams-selected",
      type: "circle",
      source: "webcams",
      filter: ["==", ["get", "id"], ""],
      paint: {
        "circle-radius": 11,
        "circle-color": "#22d3ee",
        "circle-stroke-color": "#cffafe",
        "circle-stroke-width": 3,
        "circle-blur": 0.05,
      },
    });
  }
}

function applySelectedWebcam(map: maplibregl.Map, selectedId: string | null) {
  if (!map.getLayer("webcams-selected")) return;
  map.setFilter("webcams-selected", ["==", ["get", "id"], selectedId ?? ""]);
}

function attachWebcamInteractions(
  map: maplibregl.Map,
  onSelectRef: { current: (id: string | null) => void },
) {
  if (!map.getLayer("webcams")) return;
  const flagged = map as unknown as { __webcamClickAttached?: boolean };
  if (flagged.__webcamClickAttached) return;
  flagged.__webcamClickAttached = true;

  map.on("click", "webcams", (event) => {
    const id = event.features?.[0]?.properties?.id;
    if (typeof id === "string") onSelectRef.current(id);
  });
  map.on("mouseenter", "webcams", () => {
    map.getCanvas().style.cursor = "pointer";
  });
  map.on("mouseleave", "webcams", () => {
    map.getCanvas().style.cursor = "";
  });
}

function setNdsiLayer(map: maplibregl.Map, tileUrl: string | null) {
  if (map.getLayer("ndsi-observation")) {
    map.removeLayer("ndsi-observation");
  }
  if (map.getSource("ndsi-observation")) {
    map.removeSource("ndsi-observation");
  }
  if (!tileUrl) return;

  map.addSource("ndsi-observation", {
    type: "raster",
    tiles: [tileUrl],
    tileSize: 256,
    attribution: "NivoSense NDSI",
  });
  map.addLayer(
    {
      id: "ndsi-observation",
      type: "raster",
      source: "ndsi-observation",
      paint: {
        "raster-opacity": 0.9,
        "raster-fade-duration": 120,
      },
    },
    map.getLayer("labels") ? "labels" : undefined,
  );
}

function addBasinsLayers(map: maplibregl.Map, fc: FC) {
  if (!map.getSource("basins")) {
    map.addSource("basins", {
      type: "geojson",
      data: fc as unknown as GeoJSON.FeatureCollection,
    });
  }

  if (!map.getLayer("basins-fill")) {
    map.addLayer({
      id: "basins-fill",
      type: "fill",
      source: "basins",
      paint: {
        "fill-color": "#67e8f9",
        "fill-opacity": 0.18,
      },
    });
  }

  if (!map.getLayer("basins-line")) {
    map.addLayer({
      id: "basins-line",
      type: "line",
      source: "basins",
      paint: {
        "line-color": "#67e8f9",
        "line-width": 2,
        "line-opacity": 0.85,
      },
    });
  }

  if (!map.getLayer("basins-fill-selected")) {
    map.addLayer({
      id: "basins-fill-selected",
      type: "fill",
      source: "basins",
      filter: ["==", ["get", "cod_uni"], -1],
      paint: {
        "fill-color": "#22d3ee",
        "fill-opacity": 0.35,
      },
    });
  }

  if (!map.getLayer("basins-line-selected")) {
    map.addLayer({
      id: "basins-line-selected",
      type: "line",
      source: "basins",
      filter: ["==", ["get", "cod_uni"], -1],
      paint: {
        "line-color": "#a5f3fc",
        "line-width": 3.5,
        "line-blur": 0.5,
      },
    });
  }
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

  const flagged = map as unknown as { __basinClickAttached?: boolean };
  if (flagged.__basinClickAttached) return;
  flagged.__basinClickAttached = true;

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
