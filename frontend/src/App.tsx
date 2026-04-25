import { useEffect, useState } from "react";
import Map from "./components/Map";
import TopBanner from "./components/TopBanner";
import LeftRail, { type LayerMode, type RailAction } from "./components/LeftRail";
import BasinChart from "./components/BasinChart";
import Legend from "./components/Legend";
import { prettifyBasinName } from "./lib/geo";
import type { HorizonId } from "./lib/horizons";
import type { Basin, BasinSeries } from "./lib/types";

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
  const [horizon, setHorizon] = useState<HorizonId | null>(null);
  const [railExpanded, setRailExpanded] = useState(false);
  const [layer, setLayer] = useState<LayerMode>("cover");
  const [statsOpen, setStatsOpen] = useState(false);
  const [routesOpen, setRoutesOpen] = useState(false);
  const [selectedBasinId, setSelectedBasinId] = useState<string | null>(null);

  const [basinsFC, setBasinsFC] = useState<BasinFeatureCollection | null>(null);
  const [basinSeries, setBasinSeries] = useState<BasinSeries | null>(null);
  const [seriesLoading, setSeriesLoading] = useState(false);
  const [seriesError, setSeriesError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}data/basins.geojson`)
      .then((r) => r.json())
      .then((fc: BasinFeatureCollection) => setBasinsFC(fc))
      .catch((err) => console.error("Failed to load basins:", err));
  }, []);

  const basins: Basin[] =
    basinsFC?.features.map((f) => ({
      id: String(f.properties.cod_uni),
      name: prettifyBasinName(f.properties.nom_rio_1),
    })) ?? [];

  const selectedBasin = basins.find((b) => b.id === selectedBasinId) ?? null;

  useEffect(() => {
    if (!selectedBasinId) {
      setBasinSeries(null);
      setSeriesError(null);
      setSeriesLoading(false);
      return;
    }

    const controller = new AbortController();
    const apiUrl =
      import.meta.env.VITE_API_URL ??
      (import.meta.env.DEV ? "http://localhost:8080" : "");
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
  }, [selectedBasinId]);

  const handleAction = (a: RailAction) => {
    if (a === "stats") setStatsOpen((v) => !v);
    if (a === "routes") setRoutesOpen((v) => !v);
  };

  const handleBasinSelect = (id: string | null) => {
    setSelectedBasinId(id);
    if (id && !railExpanded) setRailExpanded(true);
    if (id && !statsOpen) setStatsOpen(true);
  };

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-[#081020] text-slate-100">
      <Map
        basinsFC={basinsFC}
        selectedBasinId={selectedBasinId}
        onBasinSelect={handleBasinSelect}
      />

      <TopBanner horizon={horizon} onHorizonChange={setHorizon} />

      <LeftRail
        expanded={railExpanded}
        onToggle={() => setRailExpanded((v) => !v)}
        onExpand={() => setRailExpanded(true)}
        layer={layer}
        onLayerChange={setLayer}
        onAction={handleAction}
        statsOpen={statsOpen}
        routesOpen={routesOpen}
        basins={basins}
        selectedBasinId={selectedBasinId}
        onBasinSelect={handleBasinSelect}
      />

      <Legend layer={layer} />

      {selectedBasin && (
        <BasinChart
          basinName={selectedBasin.name}
          series={basinSeries}
          loading={seriesLoading}
          error={seriesError}
          onClose={() => setSelectedBasinId(null)}
        />
      )}
    </div>
  );
}
