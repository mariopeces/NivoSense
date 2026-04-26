import {
  MountainIcon,
  SnowflakeIcon,
  TrendIcon,
  WaterDropIcon,
  HikerIcon,
  ChevronRightIcon,
  ChevronLeftIcon,
} from "../lib/icons";
import type { ComponentType } from "react";
import type { River } from "../lib/types";

type IconComp = ComponentType<{ className?: string }>;

export type RailAction = "stats" | "routes";
export type LayerMode = "cover" | "change";
export type WaterTab = "snow" | "flow";

type Props = {
  expanded: boolean;
  onToggle: () => void;
  onExpand: () => void;
  layer: LayerMode;
  onLayerChange: (l: LayerMode) => void;
  onAction: (a: RailAction) => void;
  statsOpen: boolean;
  routesOpen: boolean;
  rivers: River[];
  riversLoading: boolean;
  riversError: string | null;
  selectedRiverId: string | null;
  onRiverSelect: (id: string | null) => void;
  waterTab: WaterTab;
  onWaterTabChange: (tab: WaterTab) => void;
};

export default function LeftRail({
  expanded,
  onToggle,
  onExpand,
  layer,
  onLayerChange,
  onAction,
  statsOpen,
  routesOpen,
  rivers,
  riversLoading,
  riversError,
  selectedRiverId,
  onRiverSelect,
  waterTab,
  onWaterTabChange,
}: Props) {
  const width = expanded ? 260 : 76;

  const wrap = (fn: () => void) => () => {
    if (!expanded) onExpand();
    fn();
  };

  return (
    <aside
      className="pointer-events-auto absolute bottom-0 left-0 top-16 z-20 flex flex-col border-r border-white/5 bg-[#081020]/65 backdrop-blur-lg transition-[width] duration-200"
      style={{ width }}
    >
      <div className="flex flex-col gap-2 overflow-y-auto p-3">
        <RegionPill
          expanded={expanded}
          label="Sierra Nevada"
          onClick={wrap(() => {})}
        />

        <div className="my-2 h-px bg-white/5" />

        <NavItem
          icon={SnowflakeIcon}
          label="Snow Cover"
          expanded={expanded}
          active={layer === "cover"}
          onClick={wrap(() => onLayerChange("cover"))}
        />
        <NavItem
          icon={TrendIcon}
          label="Snow change"
          expanded={expanded}
          active={layer === "change"}
          onClick={wrap(() => onLayerChange("change"))}
        />

        <NavItem
          icon={WaterDropIcon}
          label="Water by River"
          expanded={expanded}
          active={statsOpen}
          expandable
          isOpen={statsOpen}
          onClick={wrap(() => onAction("stats"))}
        />
        {expanded && statsOpen && (
          <RiverAccordion
            rivers={rivers}
            loading={riversLoading}
            error={riversError}
            selectedId={selectedRiverId}
            onSelect={onRiverSelect}
            waterTab={waterTab}
            onWaterTabChange={onWaterTabChange}
          />
        )}

        <NavItem
          icon={HikerIcon}
          label="Snow routes"
          expanded={expanded}
          active={routesOpen}
          expandable
          isOpen={routesOpen}
          onClick={wrap(() => onAction("routes"))}
        />
        {expanded && routesOpen && (
          <p className="px-3 pb-2 text-[11px] leading-relaxed text-slate-500">
            No routes loaded yet. Routes will appear here once the dataset is
            available.
          </p>
        )}
      </div>

      <div className="mt-auto p-3">
        <button
          onClick={onToggle}
          className="flex h-10 w-full items-center justify-center gap-2 rounded-lg border border-white/5 bg-slate-900/60 text-slate-400 transition hover:border-white/10 hover:text-slate-200"
          aria-label={expanded ? "Collapse" : "Expand"}
        >
          {expanded ? (
            <>
              <ChevronLeftIcon className="h-4 w-4" />
              <span className="text-[11px] font-medium uppercase tracking-[0.2em]">
                Collapse
              </span>
            </>
          ) : (
            <ChevronRightIcon className="h-5 w-5" />
          )}
        </button>
      </div>
    </aside>
  );
}

function RegionPill({
  expanded,
  label,
  onClick,
}: {
  expanded: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="group flex h-12 items-center gap-3 rounded-full border border-cyan-300/20 bg-cyan-400/10 px-3 text-cyan-100 shadow-[inset_0_0_0_1px_rgba(34,211,238,0.15)] hover:bg-cyan-400/15"
    >
      <MountainIcon className="h-6 w-6 shrink-0" />
      {expanded && (
        <span className="truncate text-[15px] font-medium">{label}</span>
      )}
    </button>
  );
}

function NavItem({
  icon: Icon,
  label,
  expanded,
  active,
  expandable,
  isOpen,
  onClick,
}: {
  icon: IconComp;
  label: string;
  expanded: boolean;
  active?: boolean;
  expandable?: boolean;
  isOpen?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      title={!expanded ? label : undefined}
      className={`group relative flex h-12 items-center gap-3 rounded-lg px-3 transition ${
        active
          ? "bg-cyan-400/10 text-cyan-200 shadow-[inset_0_0_0_1px_rgba(34,211,238,0.25)]"
          : "text-slate-300 hover:bg-white/5 hover:text-white"
      }`}
    >
      <Icon className="h-6 w-6 shrink-0" />
      {expanded && (
        <span className="truncate text-[15px] font-medium">{label}</span>
      )}
      {expanded && expandable && (
        <ChevronRightIcon
          className={`ml-auto h-4 w-4 transition-transform ${
            isOpen ? "rotate-90" : ""
          }`}
        />
      )}
      {active && !expanded && (
        <span className="absolute -right-0.5 top-1/2 h-6 w-0.5 -translate-y-1/2 rounded-full bg-cyan-300 shadow-[0_0_8px_rgba(34,211,238,0.8)]" />
      )}
    </button>
  );
}

function RiverAccordion({
  rivers,
  loading,
  error,
  selectedId,
  onSelect,
  waterTab,
  onWaterTabChange,
}: {
  rivers: River[];
  loading: boolean;
  error: string | null;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  waterTab: WaterTab;
  onWaterTabChange: (tab: WaterTab) => void;
}) {
  if (loading) {
    return (
      <p className="px-3 pb-2 text-[11px] leading-relaxed text-slate-500">
        Loading rivers...
      </p>
    );
  }

  if (error) {
    return (
      <p className="px-3 pb-2 text-[11px] leading-relaxed text-rose-300/80">
        {error}
      </p>
    );
  }

  if (rivers.length === 0) {
    return (
      <p className="px-3 pb-2 text-[11px] leading-relaxed text-slate-500">
        No rivers available
      </p>
    );
  }

  return (
    <div className="ml-3 flex flex-col gap-1.5 border-l border-white/5 pl-3">
      <ul className="flex flex-col gap-0.5">
        {rivers.map((r) => {
          const active = r.id === selectedId;
          return (
            <li key={r.id}>
              <button
                onClick={() => onSelect(active ? null : r.id)}
                className={`flex w-full items-center justify-between gap-2 rounded-md px-2.5 py-2 text-left text-[13px] transition ${
                  active
                    ? "bg-cyan-400/10 text-cyan-200"
                    : "text-slate-300 hover:bg-white/5 hover:text-white"
                }`}
              >
                <span className="truncate">{r.name}</span>
                {active && (
                  <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-cyan-300 shadow-[0_0_6px_rgba(34,211,238,0.9)]" />
                )}
              </button>
            </li>
          );
        })}
      </ul>

      {selectedId && (
        <div className="mt-2 flex items-center gap-1 rounded-md border border-white/5 bg-slate-900/40 p-0.5">
          <TabButton
            active={waterTab === "snow"}
            onClick={() => onWaterTabChange("snow")}
          >
            Basin snow
          </TabButton>
          <TabButton
            active={waterTab === "flow"}
            onClick={() => onWaterTabChange("flow")}
          >
            River flow
          </TabButton>
        </div>
      )}
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex-1 rounded px-2 py-1.5 text-[11px] font-medium transition ${
        active
          ? "bg-cyan-400/15 text-cyan-100 shadow-[inset_0_0_0_1px_rgba(34,211,238,0.3)]"
          : "text-slate-400 hover:text-slate-100"
      }`}
    >
      {children}
    </button>
  );
}
