import { useEffect, useState } from "react";
import Map from "./components/Map";
import TopBanner from "./components/TopBanner";
import LeftRail, { type LayerMode, type RailAction } from "./components/LeftRail";
import BasinChart from "./components/BasinChart";
import Legend from "./components/Legend";
import { prettifyBasinName } from "./lib/geo";
import type { HorizonId } from "./lib/horizons";
import type { Basin, CoverageSeriesPoint } from "./lib/types";

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

  useEffect(() => {
    fetch("/data/basins.geojson")
      .then((r) => r.json())
      .then((fc: BasinFeatureCollection) => setBasinsFC(fc))
      .catch((err) => console.error("Failed to load basins:", err));
  }, []);

  const basins: Basin[] =
    basinsFC?.features.map((f) => ({
      id: String(f.properties.cod_uni),
      name: prettifyBasinName(f.properties.nom_rio_1),
    })) ?? [];

  const basinSeries: CoverageSeriesPoint[] = [];
  const selectedBasin = basins.find((b) => b.id === selectedBasinId) ?? null;

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
    <div className="relative h-screen w-screen overflow-hidden bg-slate-950 text-slate-100">
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
          data={basinSeries}
          onClose={() => setSelectedBasinId(null)}
        />
      )}
    </div>
  );
}
