import { useEffect, useMemo, useState, type CSSProperties } from "react";
import Map from "./components/Map";
import type { Basemap } from "./lib/basemaps";
import Rail, { type Section } from "./components/Rail";
import Panel, { type SheetHeight } from "./components/Panel";
import DateBar, { type Scene } from "./components/DateBar";
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
import { staticObservationScene } from "./lib/snowObservation";
import {
  SNOW_MODEL_SCHEMA_VERSION,
  snowOverlay,
  type BasinVolumeSeries,
  type SnowLayerId,
  type SnowModelManifest,
} from "./lib/snowModel";
import {
  WEATHER_SCHEMA_VERSION,
  weatherField,
  weatherOverlay,
  type WeatherHorizon,
  type WeatherManifest,
  type WeatherVariable,
} from "./lib/weather";
import type {
  Basin,
  BasinSeries,
  FlowSeries,
  ObservationScene,
  PredictionScene,
  River,
  Webcam,
} from "./lib/types";

type BasinFeatureCollection = {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    properties: {
      cod_uni: number;
      nom_rio_1: string;
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
  const [observations, setObservations] = useState<ObservationScene[]>([]);
  const [observationsLoading, setObservationsLoading] = useState(true);
  const [predictions, setPredictions] = useState<PredictionScene[]>([]);
  const [selectedObservationDate, setSelectedObservationDate] = useState<
    string | null
  >(null);
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
  const [snowLayerId, setSnowLayerId] = useState<SnowLayerId | null>(null);
  const [volumeSeries, setVolumeSeries] = useState<BasinVolumeSeries | null>(null);
  const [volumeLoading, setVolumeLoading] = useState(false);
  const [volumeError, setVolumeError] = useState<string | null>(null);

  const apiUrl =
    import.meta.env.VITE_API_URL ??
    (import.meta.env.DEV ? "http://localhost:8080" : "");
  const snowManifestUrl = `${import.meta.env.BASE_URL}data/snow-model/manifest.json`;
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
    if (!apiUrl) return;
    fetch(`${apiUrl}/predictions`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((items: PredictionScene[]) => setPredictions(items))
      .catch((err) => console.error("Failed to load predictions:", err));
  }, [apiUrl]);

  useEffect(() => {
    const manifestUrl = new URL(
      `${import.meta.env.BASE_URL}data/observations/latest/manifest.json`,
      document.baseURI,
    ).toString();
    fetch(manifestUrl)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((payload: unknown) => [staticObservationScene(payload, manifestUrl)])
      .catch(() =>
        apiUrl
          ? fetch(`${apiUrl}/observations`).then((r) => {
              if (!r.ok) throw new Error(`HTTP ${r.status}`);
              return r.json() as Promise<ObservationScene[]>;
            })
          : ([] as ObservationScene[]),
      )
      .then((items) => {
        setObservations(items);
        setSelectedObservationDate((current) => {
          if (current && items.some((item) => item.date === current)) {
            return current;
          }
          return items.length ? items[items.length - 1].date : null;
        });
      })
      .catch((err) => console.error("Failed to load observations:", err))
      .finally(() => setObservationsLoading(false));
  }, [apiUrl]);

  const basins: Basin[] =
    basinsFC?.features.map((f) => ({
      id: String(f.properties.cod_uni),
      name: prettifyBasinName(f.properties.nom_rio_1),
      areaKm2: typeof f.properties.area_km2 === "number" ? f.properties.area_km2 : undefined,
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
  };

  const selectedObservation =
    observations.find((item) => item.date === selectedObservationDate) ?? null;
  const selectedPrediction =
    predictions.find((item) => item.date === selectedObservationDate) ?? null;
  const ndsiTileUrl = selectedObservation
    ? selectedObservation.tile_url
      ? `${apiUrl}${selectedObservation.tile_url}`
      : null
    : selectedPrediction
      ? `${apiUrl}${selectedPrediction.tile_url}`
      : null;
  const ndsiImage =
    selectedObservation?.image_url && selectedObservation.image_bbox
      ? { url: selectedObservation.image_url, bbox: selectedObservation.image_bbox }
      : null;
  const activeWeatherModel =
    weatherManifest?.models.find((model) => model.id === weatherModelId) ??
    weatherManifest?.models[0];
  const precipitationOverlay = weatherOverlay(
    weatherManifest,
    activeWeatherModel?.id ?? null,
    weatherVariable,
    weatherHorizon,
    weatherManifestUrl,
  );

  const activeSnowOverlay = snowOverlay(snowManifest, snowLayerId, snowManifestUrl);

  const handleWeatherModelChange = (modelId: string) => {
    setWeatherModelId(modelId);
    const model = weatherManifest?.models.find((item) => item.id === modelId);
    if (!weatherField(model, 24, weatherVariable)?.available) {
      setWeatherVariable("precipitation_total");
    }
  };

  const scenes: Scene[] = useMemo(
    () =>
      [
        ...observations.map((o) => ({ date: o.date, isPrediction: false })),
        ...predictions.map((p) => ({ date: p.date, isPrediction: true })),
      ].sort((a, b) => a.date.localeCompare(b.date)),
    [observations, predictions],
  );

  const panelVisible = mobile || panelOpen;
  // Pixels of map covered by the rail, panel or sheet and the date bar, so fitted bounds stay visible.
  const mapInset = useMemo(() => {
    const dateBar = tokenPx("layout-timeline-height") + tokenPx("space-8");
    if (!mobile) {
      const rail = tokenPx("layout-rail-width");
      return { left: rail + (panelOpen ? tokenPx("layout-panel-width") : 0), bottom: dateBar };
    }
    // The half sheet is 50vh in the tokens; the full sheet hides the date bar and leaves only a strip of map.
    const sheetPx = sheet === "peek" ? tokenPx("layout-sheet-peek") : viewportHeight / 2;
    return { left: 0, bottom: tokenPx("layout-tabbar-height") + sheetPx + dateBar };
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
        {/* DOM order is the tab order the spec asks for: panel, date bar, then the map and its controls. */}
        <Panel section={section} open={panelVisible} sheet={sheet} onSheet={setSheet}>
          {section === "nieve" && (
            <NieveSection
              manifest={snowManifest}
              loading={snowLoading}
              selected={snowLayerId}
              onChange={setSnowLayerId}
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
              horizon={weatherHorizon}
              onHorizon={setWeatherHorizon}
              modelId={activeWeatherModel?.id ?? null}
              onModel={handleWeatherModelChange}
              variable={weatherVariable}
              onVariable={setWeatherVariable}
            />
          )}
          {section === "metodo" && <MetodoSection />}
        </Panel>
        <DateBar
          scenes={scenes}
          loading={observationsLoading}
          selectedDate={selectedObservationDate}
          onChange={(date) => {
            setSelectedObservationDate(date);
            setWeatherHorizon(null);
          }}
          hidden={mobile && sheet === "full"}
        />
        <Legend weatherOverlay={precipitationOverlay} snowOverlay={activeSnowOverlay} />
        <Map
          basinsFC={basinsFC}
          selectedBasinId={selectedBasinId}
          ndsiTileUrl={ndsiTileUrl}
          ndsiImage={ndsiImage}
          weatherOverlay={precipitationOverlay}
          snowOverlay={activeSnowOverlay}
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
  );
}
