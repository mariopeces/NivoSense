import { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import type { StyleSpecification } from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { bboxOfGeometry } from "../lib/geo";
import type { Webcam } from "../lib/types";
import type { SnowOverlay } from "../lib/snowModel";
import type { WeatherOverlay } from "../lib/weather";
import { t } from "../lib/copy";
import { token } from "../lib/tokens";

maplibregl.setWorkerUrl(workerUrl);

const SIERRA_NEVADA_BOUNDS: [[number, number], [number, number]] = [
  [-3.55, 36.92],
  [-2.95, 37.18],
];

export type { Basemap } from "../lib/basemaps";
import type { Basemap } from "../lib/basemaps";

const IGN_ATTRIBUTION = t("mapa.atribucion_ign");

function ignWmts(service: string, layer: string) {
  return (
    `https://www.ign.es/wmts/${service}?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=${layer}` +
    "&STYLE=default&TILEMATRIXSET=GoogleMapsCompatible&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=image/jpeg"
  );
}

// Basemaps from the design spec: IGN Base gris by default (grey with hillshade, so it never competes with
// the data colours) and the IGN PNOA orthophoto for detail.
const BASEMAP_TILES: Record<Basemap, string> = {
  claro: ignWmts("ign-base", "IGNBase-gris"),
  ortofoto: ignWmts("pnoa-ma", "OI.OrthoimageCoverage"),
};

// Terrain for the 3D view: AWS Open Data Terrain Tiles (Mapzen terrarium encoding), open and CORS-enabled.
const TERRAIN_TILES = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png";
const TERRAIN_EXAGGERATION = 1.3;
const TERRAIN_PITCH = 60;

function baseStyle(basemap: Basemap): StyleSpecification {
  return {
    version: 8,
    sources: {
      basemap: {
        type: "raster",
        tiles: [BASEMAP_TILES[basemap]],
        tileSize: 256,
        maxzoom: basemap === "claro" ? 17 : 19,
        attribution: IGN_ATTRIBUTION,
      },
      terrain: {
        type: "raster-dem",
        tiles: [TERRAIN_TILES],
        tileSize: 256,
        maxzoom: 15,
        encoding: "terrarium",
        attribution: "Terrain Tiles: Mapzen, AWS Open Data",
      },
    },
    layers: [{ id: "basemap", type: "raster", source: "basemap" }],
  };
}

function applyTerrain(map: maplibregl.Map, on: boolean) {
  map.setTerrain(on ? { source: "terrain", exaggeration: TERRAIN_EXAGGERATION } : null);
}

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
  weatherOverlay: WeatherOverlay | null;
  snowOverlay: SnowOverlay | null;
  onBasinSelect: (id: string | null) => void;
  webcams: Webcam[];
  selectedWebcamId: string | null;
  onWebcamSelect: (id: string | null) => void;
  basemap: Basemap;
  terrain: boolean;
  /** Map pixels hidden behind the rail and panel, so fitted bounds stay in the visible part. */
  inset: { left: number; bottom: number };
};

export default function Map({
  basinsFC,
  selectedBasinId,
  weatherOverlay,
  snowOverlay,
  onBasinSelect,
  webcams,
  selectedWebcamId,
  onWebcamSelect,
  basemap,
  terrain,
  inset,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const basinsFCRef = useRef<FC | null>(null);
  const selectedRef = useRef<string | null>(null);
  const weatherOverlayRef = useRef<WeatherOverlay | null>(null);
  const snowOverlayRef = useRef<SnowOverlay | null>(null);
  const onBasinSelectRef = useRef(onBasinSelect);
  const webcamsRef = useRef<Webcam[]>([]);
  const selectedWebcamRef = useRef<string | null>(null);
  const onWebcamSelectRef = useRef(onWebcamSelect);
  const terrainRef = useRef(terrain);
  const insetRef = useRef(inset);
  const basemapRef = useRef(basemap);

  useEffect(() => {
    basinsFCRef.current = basinsFC;
  }, [basinsFC]);

  useEffect(() => {
    selectedRef.current = selectedBasinId;
  }, [selectedBasinId]);

  useEffect(() => {
    weatherOverlayRef.current = weatherOverlay;
  }, [weatherOverlay]);

  useEffect(() => {
    snowOverlayRef.current = snowOverlay;
  }, [snowOverlay]);

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
    insetRef.current = inset;
  }, [inset]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: baseStyle(basemapRef.current),
      bounds: SIERRA_NEVADA_BOUNDS,
      fitBoundsOptions: { padding: fitPadding(insetRef.current, 60) },
      attributionControl: { compact: true },
      locale: {
        "NavigationControl.ZoomIn": t("mapa.acercar"),
        "NavigationControl.ZoomOut": t("mapa.alejar"),
        "NavigationControl.ResetBearing": t("mapa.norte"),
        "Map.Title": t("mapa.titulo"),
        "AttributionControl.ToggleAttribution": t("mapa.alternar_atribucion"),
        "AttributionControl.MapFeedback": t("mapa.comentarios_mapa"),
      },
    });

    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");

    const setupLayers = () => {
      setWeatherLayer(map, weatherOverlayRef.current);
      setSnowLayer(map, snowOverlayRef.current);
      if (basinsFCRef.current) {
        addBasinsLayers(map, basinsFCRef.current);
        applySelected(map, selectedRef.current);
        attachBasinInteractions(map, onBasinSelectRef);
      }
      addWebcamLayers(map, webcamsRef.current);
      applySelectedWebcam(map, selectedWebcamRef.current);
      attachWebcamInteractions(map, onWebcamSelectRef);
      applyTerrain(map, terrainRef.current);
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
    if (!map || basemapRef.current === basemap) return;
    basemapRef.current = basemap;
    // A full style swap: custom sources and layers come back through the style.load handler.
    map.setStyle(baseStyle(basemap), { diff: false });
  }, [basemap]);

  useEffect(() => {
    terrainRef.current = terrain;
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    applyTerrain(map, terrain);
    map.easeTo({ pitch: terrain ? TERRAIN_PITCH : 0, duration: 600 });
  }, [terrain]);

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
    setWeatherLayer(map, weatherOverlay);
  }, [weatherOverlay]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    setSnowLayer(map, snowOverlay);
  }, [snowOverlay]);

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
            padding: fitPadding(insetRef.current, 80),
            duration: 800,
          });
        }
      } else {
        map.fitBounds(SIERRA_NEVADA_BOUNDS, {
          padding: fitPadding(insetRef.current, 60),
          duration: 600,
        });
      }
    };

    if (map.getLayer("basins-halo-selected")) {
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

function fitPadding(inset: Props["inset"], margin: number) {
  return { top: margin, right: margin, bottom: inset.bottom + margin, left: inset.left + margin };
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
        offline: webcam.offline,
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
        "circle-color": ["case", ["get", "offline"], token("color-panel"), token("color-ink")],
        "circle-stroke-color": [
          "case",
          ["get", "offline"],
          token("color-text-muted"),
          token("color-map-halo"),
        ],
        "circle-stroke-width": 1.5,
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
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 8, 14, 11],
        "circle-color": "transparent",
        "circle-stroke-color": token("color-accent"),
        "circle-stroke-width": 3,
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

function setSnowLayer(map: maplibregl.Map, overlay: SnowOverlay | null) {
  if (map.getLayer("snow-model")) {
    map.removeLayer("snow-model");
  }
  if (map.getSource("snow-model")) {
    map.removeSource("snow-model");
  }
  if (!overlay) return;

  map.addSource("snow-model", {
    type: "image",
    url: overlay.imageUrl,
    coordinates: overlay.corners as [
      [number, number],
      [number, number],
      [number, number],
      [number, number],
    ],
  });
  map.addLayer(
    {
      id: "snow-model",
      type: "raster",
      source: "snow-model",
      paint: {
        "raster-opacity": overlay.layer === "s2_true_colour" ? 1 : 0.88,
        "raster-fade-duration": 0,
        "raster-resampling": overlay.layer === "observed_snow_10m" ? "nearest" : "linear",
      },
    },
    map.getLayer("basins-fill") ? "basins-fill" : undefined,
  );
}

function setWeatherLayer(map: maplibregl.Map, overlay: WeatherOverlay | null) {
  if (map.getLayer("weather-precipitation")) {
    map.removeLayer("weather-precipitation");
  }
  if (map.getSource("weather-precipitation")) {
    map.removeSource("weather-precipitation");
  }
  if (!overlay) return;

  const [left, bottom, right, top] = overlay.bounds;
  map.addSource("weather-precipitation", {
    type: "image",
    url: overlay.imageUrl,
    coordinates: [
      [left, top],
      [right, top],
      [right, bottom],
      [left, bottom],
    ],
  });
  map.addLayer(
    {
      id: "weather-precipitation",
      type: "raster",
      source: "weather-precipitation",
      paint: { "raster-opacity": 0.78, "raster-fade-duration": 0 },
    },
    map.getLayer("basins-fill") ? "basins-fill" : undefined,
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
      // Invisible: it only gives the basins a click target; the outlines carry the drawing.
      paint: {
        "fill-color": token("color-ink"),
        "fill-opacity": 0,
      },
    });
  }

  if (!map.getLayer("basins-halo")) {
    map.addLayer({
      id: "basins-halo",
      type: "line",
      source: "basins",
      paint: { "line-color": token("color-map-halo"), "line-width": 3.5, "line-opacity": 0.9 },
    });
  }

  if (!map.getLayer("basins-line")) {
    map.addLayer({
      id: "basins-line",
      type: "line",
      source: "basins",
      paint: { "line-color": token("color-ink"), "line-width": 1.25 },
    });
  }

  if (!map.getLayer("basins-halo-selected")) {
    map.addLayer({
      id: "basins-halo-selected",
      type: "line",
      source: "basins",
      filter: ["==", ["get", "cod_uni"], -1],
      paint: { "line-color": token("color-map-halo"), "line-width": 6 },
    });
  }

  if (!map.getLayer("basins-line-selected")) {
    map.addLayer({
      id: "basins-line-selected",
      type: "line",
      source: "basins",
      filter: ["==", ["get", "cod_uni"], -1],
      paint: { "line-color": token("color-accent"), "line-width": 3 },
    });
  }
}

function applySelected(map: maplibregl.Map, selectedId: string | null) {
  if (!map.getLayer("basins-halo-selected")) return;
  const codUni = selectedId ? Number(selectedId) : -1;
  map.setFilter("basins-halo-selected", ["==", ["get", "cod_uni"], codUni]);
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
