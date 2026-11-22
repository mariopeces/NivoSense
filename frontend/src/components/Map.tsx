import { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import type { StyleSpecification } from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { bboxOfGeometry } from "../lib/geo";
import type { Webcam } from "../lib/types";
import { createWebcamMarkers, type WebcamMarkers } from "../lib/webcamMarkers";
import { Protocol } from "pmtiles";
import type { Status } from "./ui";
import type { WeatherOverlay } from "../lib/weather";
import { t } from "../lib/copy";
import { token } from "../lib/tokens";
import { basinStyle } from "../lib/basinStyle";

maplibregl.setWorkerUrl(workerUrl);
// Catalogue tiles are PMTiles archives read by HTTP range requests straight from the bucket (no tile server).
maplibregl.addProtocol("pmtiles", new Protocol().tile);

/** A catalogue layer on the map at the date it shows (its own date may be the nearest to the map date). */
export type CatalogLayer = {
  id: string;
  name: string;
  url: string;
  bounds: [number, number, number, number];
  opacity: number;
  date: string;
  status: Status;
  resampling: "nearest" | "linear";
  attribution: string;
};

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
  /** The active tab; the basins are only drawn in full on "agua". */
  section: string;
  weatherOverlay: WeatherOverlay | null;
  /** Bottom to top. */
  catalogLayers: CatalogLayer[];
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
  section,
  weatherOverlay,
  catalogLayers,
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
  const catalogLayersRef = useRef<CatalogLayer[]>([]);
  const onBasinSelectRef = useRef(onBasinSelect);
  const sectionRef = useRef(section);
  const webcamsRef = useRef<Webcam[]>([]);
  const selectedWebcamRef = useRef<string | null>(null);
  const onWebcamSelectRef = useRef(onWebcamSelect);
  const markersRef = useRef<WebcamMarkers | null>(null);
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
    catalogLayersRef.current = catalogLayers;
  }, [catalogLayers]);

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
      setCatalogLayers(map, catalogLayersRef.current);
      if (basinsFCRef.current) {
        addBasinsLayers(map, basinsFCRef.current);
        applySelected(map, selectedRef.current, sectionRef.current);
        applyBasinStyle(map, sectionRef.current);
        attachBasinInteractions(map, onBasinSelectRef, sectionRef);
      }
      applyTerrain(map, terrainRef.current);
    };

    map.on("load", setupLayers);
    map.on("style.load", setupLayers);

    mapRef.current = map;
    markersRef.current = createWebcamMarkers(map, (id) => onWebcamSelectRef.current(id));
    markersRef.current.update(webcamsRef.current, selectedWebcamRef.current);

    return () => {
      markersRef.current?.destroy();
      markersRef.current = null;
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
    applySelected(map, selectedBasinId, sectionRef.current);
    applyBasinStyle(map, sectionRef.current);
    attachBasinInteractions(map, onBasinSelectRef, sectionRef);
  }, [basinsFC]);

  useEffect(() => {
    sectionRef.current = section;
    const map = mapRef.current;
    // No isStyleLoaded() guard: it stays false while tiles load, which would skip the switch.
    if (!map) return;
    applyBasinStyle(map, section);
    applySelected(map, selectedRef.current, section);
  }, [section]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    // isStyleLoaded() is false while any source is still loading (catalogue tiles, a previous overlay), which would
    // silently drop the forecast; wait for the map to settle instead.
    if (map.isStyleLoaded()) {
      setWeatherLayer(map, weatherOverlay);
      return;
    }
    const apply = () => setWeatherLayer(map, weatherOverlay);
    map.once("idle", apply);
    return () => {
      map.off("idle", apply);
    };
  }, [weatherOverlay]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    setCatalogLayers(map, catalogLayers);
  }, [catalogLayers]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !basinsFC) return;

    const apply = () => {
      applySelected(map, selectedBasinId, sectionRef.current);
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
    markersRef.current?.update(webcams, selectedWebcamId);
  }, [webcams, selectedWebcamId]);

  return <div ref={containerRef} className="absolute inset-0" />;
}

function fitPadding(inset: Props["inset"], margin: number) {
  return { top: margin, right: margin, bottom: inset.bottom + margin, left: inset.left + margin };
}

// The archive each catalogue layer's source was created from, per map, so a date change swaps only the
// layers whose archive changed and an opacity change touches only the paint property.
const catalogSources = new WeakMap<maplibregl.Map, Map<string, string>>();

function setCatalogLayers(map: maplibregl.Map, layers: CatalogLayer[]) {
  const sources = catalogSources.get(map) ?? new globalThis.Map<string, string>();
  catalogSources.set(map, sources);
  const wanted = new globalThis.Map(layers.map((layer) => [`catalog-${layer.id}`, layer]));
  for (const [id, url] of [...sources]) {
    // A style swap drops the layer without telling us, so a missing layer counts as stale too.
    if (wanted.get(id)?.url !== url || !map.getLayer(id)) {
      if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource(id)) map.removeSource(id);
      sources.delete(id);
    }
  }
  // Under the weather overlay and the basins, above the basemap.
  const above = () => (map.getLayer("weather-precipitation") ? "weather-precipitation" : map.getLayer("basins-fill") ? "basins-fill" : undefined);
  for (const [id, layer] of wanted) {
    if (!sources.has(id)) {
      map.addSource(id, { type: "raster", url: layer.url, tileSize: 512, bounds: layer.bounds, attribution: layer.attribution });
      map.addLayer(
        {
          id,
          type: "raster",
          source: id,
          paint: { "raster-opacity": layer.opacity, "raster-fade-duration": 0, "raster-resampling": layer.resampling },
        },
        above(),
      );
      sources.set(id, layer.url);
    } else {
      map.setPaintProperty(id, "raster-opacity", layer.opacity);
    }
  }
  for (const id of wanted.keys()) map.moveLayer(id, above());
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
      // Light fill on the Agua tab only (applyBasinStyle); at opacity 0 it still takes clicks.
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

function applyBasinStyle(map: maplibregl.Map, section: string) {
  if (!map.getLayer("basins-fill")) return;
  const style = basinStyle(section);
  map.setPaintProperty("basins-fill", "fill-opacity", style.fillOpacity);
  map.setPaintProperty("basins-line", "line-width", style.lineWidth);
  map.setPaintProperty("basins-line", "line-opacity", style.lineOpacity);
  map.setPaintProperty("basins-halo", "line-opacity", style.haloOpacity);
}

function applySelected(map: maplibregl.Map, selectedId: string | null, section: string) {
  if (!map.getLayer("basins-halo-selected")) return;
  const codUni = selectedId && basinStyle(section).interactive ? Number(selectedId) : -1;
  map.setFilter("basins-halo-selected", ["==", ["get", "cod_uni"], codUni]);
  map.setFilter("basins-line-selected", ["==", ["get", "cod_uni"], codUni]);
}

function attachBasinInteractions(
  map: maplibregl.Map,
  onSelectRef: { current: (id: string | null) => void },
  sectionRef: { current: string },
) {
  if (!map.getLayer("basins-fill")) return;

  const flagged = map as unknown as { __basinClickAttached?: boolean };
  if (flagged.__basinClickAttached) return;
  flagged.__basinClickAttached = true;

  map.on("click", "basins-fill", (e) => {
    if (!basinStyle(sectionRef.current).interactive) return;
    const feature = e.features?.[0];
    if (!feature) return;
    const codUni = feature.properties?.cod_uni;
    if (codUni == null) return;
    onSelectRef.current(String(codUni));
  });

  map.on("mouseenter", "basins-fill", () => {
    if (!basinStyle(sectionRef.current).interactive) return;
    map.getCanvas().style.cursor = "pointer";
  });
  map.on("mouseleave", "basins-fill", () => {
    map.getCanvas().style.cursor = "";
  });
}
