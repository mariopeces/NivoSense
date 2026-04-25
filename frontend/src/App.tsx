import { useState } from "react";
import Map from "./components/Map";
import TopBanner from "./components/TopBanner";
import LeftRail, { type LayerMode, type RailAction } from "./components/LeftRail";
import StatsModal from "./components/StatsModal";
import BasinChart from "./components/BasinChart";
import Legend from "./components/Legend";
import type { HorizonId } from "./lib/horizons";
import type { Basin, CoverageSeriesPoint } from "./lib/types";

export default function App() {
  const [date, setDate] = useState<Date>(new Date());
  const [horizon, setHorizon] = useState<HorizonId | null>(null);
  const [railExpanded, setRailExpanded] = useState(false);
  const [layer, setLayer] = useState<LayerMode>("cover");
  const [statsOpen, setStatsOpen] = useState(false);
  const [routesOpen, setRoutesOpen] = useState(false);
  const [selectedBasinId, setSelectedBasinId] = useState<string | null>(null);

  const basins: Basin[] = [];
  const basinSeries: CoverageSeriesPoint[] = [];
  const selectedBasin = basins.find((b) => b.id === selectedBasinId) ?? null;

  const handleAction = (a: RailAction) => {
    if (a === "stats") setStatsOpen((v) => !v);
    if (a === "routes") setRoutesOpen((v) => !v);
  };

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-slate-950 text-slate-100">
      <Map />

      <TopBanner
        date={date}
        onDateChange={setDate}
        horizon={horizon}
        onHorizonChange={setHorizon}
      />

      <LeftRail
        expanded={railExpanded}
        onToggle={() => setRailExpanded((v) => !v)}
        layer={layer}
        onLayerChange={setLayer}
        onAction={handleAction}
        statsOpen={statsOpen}
        routesOpen={routesOpen}
      />

      <Legend layer={layer} />

      {selectedBasin && (
        <BasinChart
          basinName={selectedBasin.name}
          data={basinSeries}
          onClose={() => setSelectedBasinId(null)}
        />
      )}

      <StatsModal
        open={statsOpen}
        basins={basins}
        onClose={() => setStatsOpen(false)}
        onSelect={setSelectedBasinId}
      />
    </div>
  );
}
