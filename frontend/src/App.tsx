import { useEffect, useState } from "react";
import Map from "./components/Map";
import TopBanner from "./components/TopBanner";
import LeftRail, {
  type LayerMode,
  type RailAction,
  type WaterTab,
} from "./components/LeftRail";
import BasinChart from "./components/BasinChart";
import RiverFlowChart from "./components/RiverFlowChart";
import Legend from "./components/Legend";
import { prettifyBasinName } from "./lib/geo";
import type {
  Basin,
  BasinSeries,
  FlowSeries,
  ObservationScene,
  River,
} from "./lib/types";

type BasinFeatureCollection = {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    properties: {
      cod_uni: number;
      nom_rio_1: string;
      [k: string]: unknown;
    };
    geometry: { type: string; coordinates: unknown };
  }>;
};

export default function App() {
  const [railExpanded, setRailExpanded] = useState(false);
  const [layer, setLayer] = useState<LayerMode>("cover");
  const [statsOpen, setStatsOpen] = useState(false);
  const [routesOpen, setRoutesOpen] = useState(false);
  const [selectedBasinId, setSelectedBasinId] = useState<string | null>(null);
  const [selectedRiverId, setSelectedRiverId] = useState<string | null>(null);
  const [waterTab, setWaterTab] = useState<WaterTab>("snow");

  const [basinsFC, setBasinsFC] = useState<BasinFeatureCollection | null>(null);
  const [rivers, setRivers] = useState<River[]>([]);
  const [riversLoading, setRiversLoading] = useState(true);
  const [riversError, setRiversError] = useState<string | null>(null);
  const [observations, setObservations] = useState<ObservationScene[]>([]);
  const [selectedObservationDate, setSelectedObservationDate] = useState<
    string | null
  >(null);
  const [basinSeries, setBasinSeries] = useState<BasinSeries | null>(null);
  const [seriesLoading, setSeriesLoading] = useState(false);
  const [seriesError, setSeriesError] = useState<string | null>(null);
  const [flowSeries, setFlowSeries] = useState<FlowSeries | null>(null);
  const [flowLoading, setFlowLoading] = useState(false);
  const [flowError, setFlowError] = useState<string | null>(null);

  const apiUrl =
    import.meta.env.VITE_API_URL ??
    (import.meta.env.DEV ? "http://localhost:8080" : "");

  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}data/basins.geojson`)
      .then((r) => r.json())
      .then((fc: BasinFeatureCollection) => setBasinsFC(fc))
      .catch((err) => console.error("Failed to load basins:", err));
  }, []);

  useEffect(() => {
    setRiversLoading(true);
    setRiversError(null);
    fetch(`${apiUrl}/rivers`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((items: River[]) => setRivers(items))
      .catch((err) => {
        console.error("Failed to load rivers:", err);
        setRiversError("Could not load rivers");
      })
      .finally(() => setRiversLoading(false));
  }, [apiUrl]);

  useEffect(() => {
    fetch(`${apiUrl}/observations?start=2023-10-01&end=2024-09-30`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((items: ObservationScene[]) => {
        setObservations(items);
        setSelectedObservationDate((current) => {
          if (current && items.some((item) => item.date === current)) {
            return current;
          }
          return items.length ? items[items.length - 1].date : null;
        });
      })
      .catch((err) => console.error("Failed to load observations:", err));
  }, [apiUrl]);

  const basins: Basin[] =
    basinsFC?.features.map((f) => ({
      id: String(f.properties.cod_uni),
      name: prettifyBasinName(f.properties.nom_rio_1),
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

    const controller = new AbortController();
    setSeriesLoading(true);
    setSeriesError(null);

    fetch(
      `${apiUrl}/basins/${selectedBasinId}/snow-series?hydrological_year=2024`,
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
        setSeriesError("Could not load snow evolution");
      })
      .finally(() => {
        if (!controller.signal.aborted) setSeriesLoading(false);
      });

    return () => controller.abort();
  }, [selectedBasinId, apiUrl]);

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
        setFlowError(
          err.message === "flow_not_uploaded"
            ? "Flow data not uploaded yet for this river"
            : "Could not load river flow",
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setFlowLoading(false);
      });

    return () => controller.abort();
  }, [selectedRiverId, apiUrl]);

  const handleAction = (a: RailAction) => {
    if (a === "stats") setStatsOpen((v) => !v);
    if (a === "routes") setRoutesOpen((v) => !v);
  };

  const handleBasinSelect = (basinId: string | null) => {
    setSelectedBasinId(basinId);
    if (basinId) {
      const river = rivers.find((r) => String(r.basin_cod_uni) === basinId);
      setSelectedRiverId(river ? river.id : null);
      if (!railExpanded) setRailExpanded(true);
      if (!statsOpen) setStatsOpen(true);
    } else {
      setSelectedRiverId(null);
    }
  };

  const handleRiverSelect = (riverId: string | null) => {
    setSelectedRiverId(riverId);
    if (riverId) {
      if (!railExpanded) setRailExpanded(true);
      if (!statsOpen) setStatsOpen(true);
    } else {
      setSelectedBasinId(null);
    }
  };

  const handleClose = () => {
    setSelectedRiverId(null);
    setSelectedBasinId(null);
  };

  const selectedObservation =
    observations.find((item) => item.date === selectedObservationDate) ?? null;
  const ndsiTileUrl = selectedObservation
    ? `${apiUrl}${selectedObservation.tile_url}`
    : null;

  const showFlowChart =
    selectedRiver !== null && waterTab === "flow";
  const showSnowChart =
    selectedBasin !== null && !showFlowChart;

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-[#081020] text-slate-100">
      <Map
        basinsFC={basinsFC}
        selectedBasinId={selectedBasinId}
        ndsiTileUrl={ndsiTileUrl}
        onBasinSelect={handleBasinSelect}
      />

      <TopBanner
        observations={observations}
        selectedDate={selectedObservationDate}
        onDateChange={setSelectedObservationDate}
      />

      <LeftRail
        expanded={railExpanded}
        onToggle={() => setRailExpanded((v) => !v)}
        onExpand={() => setRailExpanded(true)}
        layer={layer}
        onLayerChange={setLayer}
        onAction={handleAction}
        statsOpen={statsOpen}
        routesOpen={routesOpen}
        rivers={rivers}
        riversLoading={riversLoading}
        riversError={riversError}
        selectedRiverId={selectedRiverId}
        onRiverSelect={handleRiverSelect}
        waterTab={waterTab}
        onWaterTabChange={setWaterTab}
      />

      <Legend layer={layer} />

      {showSnowChart && selectedBasin && (
        <BasinChart
          basinName={selectedBasin.name}
          series={basinSeries}
          loading={seriesLoading}
          error={seriesError}
          onClose={handleClose}
        />
      )}

      {showFlowChart && selectedRiver && (
        <RiverFlowChart
          river={selectedRiver}
          series={flowSeries}
          loading={flowLoading}
          error={flowError}
          onClose={handleClose}
        />
      )}
    </div>
  );
}
