import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";
import Map, { type Basemap } from "./components/Map";
import CreditBar from "./components/CreditBar";
import Rail, { type Section } from "./components/Rail";
import Panel, { type SheetHeight } from "./components/Panel";
import Timeline from "./components/Timeline";
import NieveSection from "./components/NieveSection";
import AguaSection from "./components/AguaSection";
import WebcamsSection from "./components/WebcamsSection";
import MeteoSection from "./components/MeteoSection";
import MetodoSection from "./components/MetodoSection";
import BasinChart from "./components/BasinChart";
import RiverFlowChart from "./components/RiverFlowChart";
import Legend from "./components/Legend";
import SnowVolumeChart from "./components/SnowVolumeChart";
import { t } from "./lib/copy";
import { useMediaQuery } from "./lib/useMediaQuery";
import { useViewportHeight } from "./lib/useViewportHeight";
import { tokenPx } from "./lib/tokens";
import { prettifyBasinName } from "./lib/geo";
import { currentHydrologicalYear } from "./lib/horizons";
import { fetchCatalog, type CatalogState } from "./lib/catalog";
import { STATUS_OF, buildTimeline, todayInMadrid } from "./lib/timeline";
import { readUrlState, writeUrlState, type VisibleLayers } from "./lib/urlState";
import { catalogRoot, entryFor, layerSpecs, pmtilesUrl } from "./lib/layers";
import type { CatalogLayer } from "./components/Map";
import {
  SNOW_MODEL_SCHEMA_VERSION,
  type BasinVolumeSeries,
  type SnowModelManifest,
} from "./lib/snowModel";
import {
  WEATHER_HORIZONS,
  WEATHER_SCHEMA_VERSION,
  weatherField,
  weatherOverlay,
  resolveHorizon,
  type WeatherHorizon,
  type WeatherManifest,
  type WeatherVariable,
} from "./lib/weather";
import type { Basin, BasinSeries, FlowSeries, River, Webcam } from "./lib/types";

type BasinFeatureCollection = {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    properties: {
      cod_uni: number;
      nom_rio_1: string;
      domain_area_km2?: number;
      area_km2?: number;
      [k: string]: unknown;
    };
    geometry: { type: string; coordinates: unknown };
  }>;
};

export default function App() {
  const [section, setSection] = useState<Section>("nieve");
  const [panelOpen, setPanelOpen] = useState(true);
  const [sheet, setSheet] = useState<SheetHeight>("peek");
  const [basemap, setBasemap] = useState<Basemap>("claro");
  const [terrain, setTerrain] = useState(false);
  const mobile = useMediaQuery("(max-width: 767px)");
  const viewportHeight = useViewportHeight();
  const [selectedBasinId, setSelectedBasinId] = useState<string | null>(null);
  const [selectedRiverId, setSelectedRiverId] = useState<string | null>(null);
  const [selectedWebcamId, setSelectedWebcamId] = useState<string | null>(null);

  const [basinsFC, setBasinsFC] = useState<BasinFeatureCollection | null>(null);
  const [basinsLoading, setBasinsLoading] = useState(true);
  const [rivers, setRivers] = useState<River[]>([]);
  const [initialUrl] = useState(() => readUrlState(window.location.search));
  const [catalog, setCatalog] = useState<CatalogState>({ kind: "loading" });
  const [catalogAttempt, setCatalogAttempt] = useState(0);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [basinSeries, setBasinSeries] = useState<BasinSeries | null>(null);
  const [seriesLoading, setSeriesLoading] = useState(false);
  const [seriesError, setSeriesError] = useState<string | null>(null);
  const [flowSeries, setFlowSeries] = useState<FlowSeries | null>(null);
  const [flowLoading, setFlowLoading] = useState(false);
  const [flowError, setFlowError] = useState<string | null>(null);
  const [hydrologicalYear, setHydrologicalYear] = useState<number>(currentHydrologicalYear());
  const [webcams, setWebcams] = useState<Webcam[]>([]);
  const [webcamsLoading, setWebcamsLoading] = useState(true);
  const [webcamsError, setWebcamsError] = useState<string | null>(null);
  const [weatherManifest, setWeatherManifest] = useState<WeatherManifest | null>(null);
  const [weatherHorizon, setWeatherHorizon] = useState<WeatherHorizon | null>(null);
  const [weatherModelId, setWeatherModelId] = useState<string | null>(null);
  const [weatherVariable, setWeatherVariable] =
    useState<WeatherVariable>("precipitation_total");
  const [weatherLoading, setWeatherLoading] = useState(true);
  const [snowManifest, setSnowManifest] = useState<SnowModelManifest | null>(null);
  const [snowLoading, setSnowLoading] = useState(true);
  const [visible, setVisible] = useState<VisibleLayers>(initialUrl.layers);
  const [layersSettled, setLayersSettled] = useState(false);
  const [volumeSeries, setVolumeSeries] = useState<BasinVolumeSeries | null>(null);
  const [volumeLoading, setVolumeLoading] = useState(false);
  const [volumeError, setVolumeError] = useState<string | null>(null);

  const apiUrl =
    import.meta.env.VITE_API_URL ??
    (import.meta.env.DEV ? "http://localhost:8080" : "");
  const snowManifestUrl = `${import.meta.env.BASE_URL}data/snow-model/manifest.json`;
  const catalogUrl = import.meta.env.VITE_CATALOG_URL;
  const weatherManifestUrl =
    import.meta.env.VITE_WEATHER_MANIFEST_URL ??
    `${import.meta.env.BASE_URL}weather/manifest.json`;

  useEffect(() => {
    fetch(snowManifestUrl)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((payload: SnowModelManifest) => {
        if (payload.schema_version !== SNOW_MODEL_SCHEMA_VERSION) {
          throw new Error(`Unsupported snow model manifest version ${payload.schema_version}`);
        }
        setSnowManifest(payload);
      })
      .catch((error) => console.error("Failed to load the snow model:", error))
      .finally(() => setSnowLoading(false));
  }, [snowManifestUrl]);

  useEffect(() => {
    const seriesPath = snowManifest?.basins.find((item) => item.id === selectedBasinId)?.series;
    setVolumeSeries(null);
    setVolumeError(null);
    if (!seriesPath) {
      setVolumeLoading(false);
      return;
    }
    const controller = new AbortController();
    setVolumeLoading(true);
    fetch(new URL(seriesPath, new URL(snowManifestUrl, window.location.href)), {
      signal: controller.signal,
    })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((payload: BasinVolumeSeries) => setVolumeSeries(payload))
      .catch((error) => {
        if (error.name === "AbortError") return;
        console.error("Failed to load the snow volume series:", error);
        setVolumeError(t("error.serie"));
      })
      .finally(() => {
        if (!controller.signal.aborted) setVolumeLoading(false);
      });
    return () => controller.abort();
  }, [snowManifest, selectedBasinId, snowManifestUrl]);

  useEffect(() => {
    fetch(weatherManifestUrl)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((payload: WeatherManifest) => {
        if (payload.schema_version !== WEATHER_SCHEMA_VERSION) {
          throw new Error(`Unsupported weather manifest version ${payload.schema_version}`);
        }
        setWeatherManifest(payload);
      })
      .catch((error) => console.error("Failed to load weather forecasts:", error))
      .finally(() => setWeatherLoading(false));
  }, [weatherManifestUrl]);

  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}data/basins.geojson`)
      .then((r) => r.json())
      .then((fc: BasinFeatureCollection) => setBasinsFC(fc))
      .catch((err) => console.error("Failed to load basins:", err))
      .finally(() => setBasinsLoading(false));
  }, []);

  useEffect(() => {
    setWebcamsLoading(true);
    fetch(`${import.meta.env.BASE_URL}data/webcams.json`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((items: Webcam[]) => setWebcams(items))
      .catch((err) => {
        console.error("Failed to load webcams:", err);
        setWebcamsError(t("error.webcams"));
      })
      .finally(() => setWebcamsLoading(false));
  }, []);

  useEffect(() => {
    if (!apiUrl) return;
    fetch(`${apiUrl}/rivers`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((items: River[]) => setRivers(items))
      .catch((err) => console.error("Failed to load rivers:", err));
  }, [apiUrl]);

  useEffect(() => {
    const controller = new AbortController();
    setCatalog({ kind: "loading" });
    fetchCatalog(catalogUrl, controller.signal)
      .then(setCatalog)
      .catch((error) => {
        if (error.name === "AbortError") return;
        console.error("Failed to load the catalogue:", error);
        setCatalog({ kind: "error" });
      });
    return () => controller.abort();
  }, [catalogUrl, catalogAttempt]);

  const timeline = useMemo(
    () => (catalog.kind === "ready" ? buildTimeline(catalog.index, todayInMadrid()) : null),
    [catalog],
  );

  // A date from a shared link is kept when it is on the track; otherwise the map opens on the latest product.
  useEffect(() => {
    if (!timeline) return;
    setSelectedDate((current) => {
      const wanted = current ?? initialUrl.date;
      if (wanted && timeline.days.some((day) => day.date === wanted)) return wanted;
      return timeline.days[timeline.latestIndex].date;
    });
  }, [timeline, initialUrl.date]);

  // Once the catalogue answers, a shared link keeps the layers that exist; without one, the map opens on the
  // true colour and the first snow layer that has products.
  useEffect(() => {
    if (layersSettled || (catalog.kind !== "ready" && catalog.kind !== "missing")) return;
    const index = catalog.kind === "ready" ? catalog.index : null;
    const published = (id: string) => (index?.layers[id]?.entries.length ?? 0) > 0;
    setVisible((current) => {
      if (initialUrl.layers.length) return current.filter((layer) => published(layer.id));
      const specs = layerSpecs(index).filter((spec) => published(spec.id));
      const snow = specs.find((spec) => spec.group === "nieve");
      const image = specs.find((spec) => spec.group === "imagen");
      return [image, snow].flatMap((spec) => (spec ? [{ id: spec.id, opacity: 100 }] : []));
    });
    setLayersSettled(true);
  }, [catalog, layersSettled, initialUrl.layers]);

  useEffect(() => {
    // Until the catalogue and the timeline answer, keep what the link asked for.
    const date = selectedDate ?? (catalog.kind === "loading" || timeline ? initialUrl.date : null);
    const search = writeUrlState(window.location.search, { date, layers: visible });
    if (search !== window.location.search) {
      window.history.replaceState(window.history.state, "", `${window.location.pathname}${search}${window.location.hash}`);
    }
  }, [selectedDate, visible, catalog.kind, timeline, initialUrl.date]);

  const toggleLayer = useCallback((id: string) => {
    setVisible((current) =>
      current.some((layer) => layer.id === id)
        ? current.filter((layer) => layer.id !== id)
        : [...current, { id, opacity: 100 }],
    );
  }, []);
  const setLayerOpacity = useCallback((id: string, opacity: number) => {
    setVisible((current) => current.map((layer) => (layer.id === id ? { ...layer, opacity } : layer)));
  }, []);

  // Draw order: the image at the bottom, then the snow layers with the top of the panel list on top.
  const mapLayers: CatalogLayer[] = useMemo(() => {
    if (catalog.kind !== "ready" || !catalogUrl || !selectedDate) return [];
    const root = catalogRoot(catalogUrl);
    const specs = layerSpecs(catalog.index);
    const ordered = [...specs.filter((spec) => spec.group === "imagen"), ...specs.filter((spec) => spec.group === "nieve").reverse()];
    return ordered.flatMap((spec) => {
      const shown = visible.find((layer) => layer.id === spec.id);
      const found = shown && entryFor(catalog.index.layers[spec.id]?.entries ?? [], selectedDate);
      if (!shown || !found) return [];
      return [
        {
          id: spec.id,
          name: spec.copy ? t(`capa.${spec.copy}.nombre`) : spec.id,
          url: pmtilesUrl(root, found.entry),
          bounds: found.entry.bounds,
          opacity: shown.opacity / 100,
          date: found.entry.date,
          status: STATUS_OF[found.entry.status],
          // Data layers show their real pixels; only the true colour image is smoothed.
          resampling: spec.ramp ? ("nearest" as const) : ("linear" as const),
          // Every catalogue layer is made from Sentinel-2 (the model assimilates it), which asks for this credit.
          attribution: t("mapa.atribucion_s2", { anio: found.entry.date.slice(0, 4) }),
        },
      ];
    });
  }, [catalog, catalogUrl, selectedDate, visible]);

  const handleDateChange = useCallback((date: string) => {
    setSelectedDate(date);
    setWeatherHorizon(null);
  }, []);

  const basins: Basin[] =
    basinsFC?.features.map((f) => ({
      id: String(f.properties.cod_uni),
      name: prettifyBasinName(f.properties.nom_rio_1),
      areaKm2: [f.properties.domain_area_km2, f.properties.area_km2].find((v) => typeof v === "number"),
    })) ?? [];

  const selectedBasin = basins.find((b) => b.id === selectedBasinId) ?? null;
  const selectedRiver =
    rivers.find((r) => r.id === selectedRiverId) ?? null;

  useEffect(() => {
    if (!selectedRiverId || rivers.length === 0) return;
    const river = rivers.find((r) => r.id === selectedRiverId);
    if (river) setSelectedBasinId(String(river.basin_cod_uni));
  }, [selectedRiverId, rivers]);

  useEffect(() => {
    if (!selectedBasinId) {
      setBasinSeries(null);
      setSeriesError(null);
      setSeriesLoading(false);
      return;
    }
    if (!apiUrl) {
      setBasinSeries(null);
      setSeriesError(null);
      return;
    }

    const controller = new AbortController();
    setSeriesLoading(true);
    setSeriesError(null);

    fetch(
      `${apiUrl}/basins/${selectedBasinId}/snow-series?hydrological_year=${hydrologicalYear}&cadence=all`,
      { signal: controller.signal },
    )
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((payload: BasinSeries) => setBasinSeries(payload))
      .catch((err) => {
        if (err.name === "AbortError") return;
        console.error("Failed to load basin series:", err);
        setSeriesError(t("error.serie"));
      })
      .finally(() => {
        if (!controller.signal.aborted) setSeriesLoading(false);
      });

    return () => controller.abort();
  }, [selectedBasinId, hydrologicalYear, apiUrl]);

  useEffect(() => {
    if (!selectedRiverId) {
      setFlowSeries(null);
      setFlowError(null);
      setFlowLoading(false);
      return;
    }

    const controller = new AbortController();
    setFlowLoading(true);
    setFlowError(null);

    if (!apiUrl) {
      setFlowLoading(false);
      return;
    }

    fetch(`${apiUrl}/rivers/${selectedRiverId}/flow`, {
      signal: controller.signal,
    })
      .then((r) => {
        if (r.status === 404) throw new Error("flow_not_uploaded");
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((payload: FlowSeries) => setFlowSeries(payload))
      .catch((err) => {
        if (err.name === "AbortError") return;
        console.error("Failed to load river flow:", err);
        if (err.message !== "flow_not_uploaded") setFlowError(t("error.serie"));
      })
      .finally(() => {
        if (!controller.signal.aborted) setFlowLoading(false);
      });

    return () => controller.abort();
  }, [selectedRiverId, apiUrl]);

  const handleWebcamSelect = (webcamId: string | null) => {
    setSelectedWebcamId(webcamId);
    if (webcamId) {
      setSection("webcams");
      setPanelOpen(true);
      setSelectedBasinId(null);
      setSelectedRiverId(null);
    }
  };

  // The one path for basin selection, from the map and from the Agua list alike.
  const handleBasinSelect = (basinId: string | null) => {
    setSelectedBasinId(basinId);
    if (basinId) {
      const river = rivers.find((r) => String(r.basin_cod_uni) === basinId);
      setSelectedRiverId(river ? river.id : null);
      setSection("agua");
      setPanelOpen(true);
      if (sheet === "peek") setSheet("half");
    } else {
      setSelectedRiverId(null);
    }
  };

  const handleSection = (next: Section) => {
    if (next === section && mobile) setSheet(sheet === "peek" ? "half" : "peek");
    setSection(next);
    setPanelOpen(true);
    // Opening the forecast tab shows a forecast right away instead of an empty map until a horizon is picked.
    if (next === "meteo" && weatherHorizon === null) {
      setWeatherHorizon(resolveHorizon(activeWeatherModel, weatherVariable, WEATHER_HORIZONS[0]));
    }
  };

  const activeWeatherModel =
    weatherManifest?.models.find((model) => model.id === weatherModelId) ??
    weatherManifest?.models[0];
  // A horizon the chosen model does not offer (AEMET stops at 48 h) falls back instead of leaving the map empty.
  const effectiveHorizon =
    weatherHorizon === null ? null : resolveHorizon(activeWeatherModel, weatherVariable, weatherHorizon);
  const precipitationOverlay = useMemo(
    () =>
      weatherOverlay(
        weatherManifest,
        activeWeatherModel?.id ?? null,
        weatherVariable,
        effectiveHorizon,
        weatherManifestUrl,
      ),
    [weatherManifest, activeWeatherModel?.id, weatherVariable, effectiveHorizon, weatherManifestUrl],
  );

  const handleWeatherModelChange = (modelId: string) => {
    setWeatherModelId(modelId);
    const model = weatherManifest?.models.find((item) => item.id === modelId);
    if (!weatherField(model, 24, weatherVariable)?.available) {
      setWeatherVariable("precipitation_total");
    }
  };

  const panelVisible = mobile || panelOpen;
  // Pixels of map covered by the rail, panel or sheet and the timeline, so fitted bounds stay visible.
  const mapInset = useMemo(() => {
    const timelineHeight = tokenPx("layout-timeline-height") + tokenPx("space-8");
    if (!mobile) {
      const rail = tokenPx("layout-rail-width");
      return { left: rail + (panelOpen ? tokenPx("layout-panel-width") : 0), bottom: timelineHeight };
    }
    // The half sheet is 50vh in the tokens; the full sheet hides the timeline and leaves only a strip of map.
    const sheetPx = sheet === "peek" ? tokenPx("layout-sheet-peek") : viewportHeight / 2;
    return { left: 0, bottom: tokenPx("layout-tabbar-height") + sheetPx + timelineHeight };
  }, [mobile, panelOpen, sheet, viewportHeight]);
  const shellStyle = {
    "--shell-panel-offset": panelOpen ? "var(--layout-panel-width)" : "0px",
    "--sheet-height":
      sheet === "full"
        ? "calc(100% - var(--layout-tabbar-height) - var(--space-12))"
        : `var(--layout-sheet-${sheet})`,
  } as CSSProperties;

  return (
    <div className="relative h-full w-full overflow-hidden bg-panel-soft font-body text-text" style={shellStyle}>
      <div className="absolute inset-x-0 top-0 bottom-credit">
        <Rail
          section={section}
          onSection={handleSection}
          panelOpen={panelOpen}
          onTogglePanel={() => setPanelOpen((open) => !open)}
          basemap={basemap}
          onBasemap={setBasemap}
          terrain={terrain}
          onToggleTerrain={() => setTerrain((on) => !on)}
        />
        <main className="absolute inset-0" aria-label={t("app.descripcion")}>
          <h1 className="sr-only">{t("app.nombre")}</h1>
          {/* DOM order is the tab order the spec asks for: panel, timeline, then the map and its controls. */}
          <Panel section={section} open={panelVisible} sheet={sheet} onSheet={setSheet}>
            {section === "nieve" && (
              <NieveSection
                catalog={catalog}
                date={selectedDate}
                visible={visible}
                onToggle={toggleLayer}
                onOpacity={setLayerOpacity}
                onDate={handleDateChange}
                onMethod={() => handleSection("metodo")}
                onRetry={() => setCatalogAttempt((attempt) => attempt + 1)}
              />
            )}
            {section === "agua" && (
              <AguaSection
                basins={basins}
                loading={basinsLoading}
                selectedId={selectedBasinId}
                onSelect={handleBasinSelect}
              >
                {selectedBasin && !apiUrl && (
                  <SnowVolumeChart
                    basin={snowManifest?.basins.find((item) => item.id === selectedBasin.id) ?? null}
                    manifest={snowManifest}
                    series={volumeSeries}
                    loading={volumeLoading || snowLoading}
                    error={volumeError}
                  />
                )}
                {selectedBasin && apiUrl && (
                  <BasinChart
                    series={basinSeries}
                    loading={seriesLoading}
                    error={seriesError}
                    hydrologicalYear={hydrologicalYear}
                    onYearChange={setHydrologicalYear}
                  />
                )}
                {selectedRiver && (
                  <RiverFlowChart river={selectedRiver} series={flowSeries} loading={flowLoading} error={flowError} />
                )}
              </AguaSection>
            )}
            {section === "webcams" && (
              <WebcamsSection
                webcams={webcams}
                loading={webcamsLoading}
                error={webcamsError}
                selectedId={selectedWebcamId}
                onSelect={handleWebcamSelect}
              />
            )}
            {section === "meteo" && (
              <MeteoSection
                manifest={weatherManifest}
                loading={weatherLoading}
                horizon={effectiveHorizon}
                onHorizon={setWeatherHorizon}
                modelId={activeWeatherModel?.id ?? null}
                onModel={handleWeatherModelChange}
                variable={weatherVariable}
                onVariable={setWeatherVariable}
              />
            )}
            {section === "metodo" && <MetodoSection />}
          </Panel>
          <Timeline
            catalog={catalog}
            model={timeline}
            selectedDate={selectedDate}
            onChange={handleDateChange}
            onRetry={() => setCatalogAttempt((attempt) => attempt + 1)}
            hidden={mobile && sheet === "full"}
            mobile={mobile}
          />
          <Legend weatherOverlay={precipitationOverlay} layers={mapLayers} />
          <Map
            basinsFC={basinsFC}
            selectedBasinId={selectedBasinId}
            section={section}
            weatherOverlay={precipitationOverlay}
            catalogLayers={mapLayers}
            onBasinSelect={handleBasinSelect}
            webcams={webcams}
            selectedWebcamId={selectedWebcamId}
            onWebcamSelect={handleWebcamSelect}
            basemap={basemap}
            terrain={terrain}
            inset={mapInset}
          />
        </main>
      </div>
      <CreditBar />
    </div>
  );
}
