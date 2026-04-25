import {
  MountainIcon,
  SnowflakeIcon,
  TrendIcon,
  StatsIcon,
  HikerIcon,
  ChevronRightIcon,
  ChevronLeftIcon,
} from "../lib/icons";
import type { ComponentType } from "react";

type IconComp = ComponentType<{ className?: string }>;

export type RailAction = "stats" | "routes";
export type LayerMode = "cover" | "change";

type Props = {
  expanded: boolean;
  onToggle: () => void;
  onExpand: () => void;
  layer: LayerMode;
  onLayerChange: (l: LayerMode) => void;
  onAction: (a: RailAction) => void;
  statsOpen: boolean;
  routesOpen: boolean;
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
}: Props) {
  const width = expanded ? 240 : 76;

  const wrap = (fn: () => void) => () => {
    if (!expanded) onExpand();
    fn();
  };

  return (
    <aside
      className="pointer-events-auto absolute bottom-0 left-0 top-16 z-20 flex flex-col border-r border-white/5 bg-slate-950/80 backdrop-blur-xl transition-[width] duration-200"
      style={{ width }}
    >
      <div className="flex flex-col gap-2 p-3">
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
          icon={StatsIcon}
          label="Stats"
          expanded={expanded}
          active={statsOpen}
          onClick={wrap(() => onAction("stats"))}
        />
        <NavItem
          icon={HikerIcon}
          label="Snow routes"
          expanded={expanded}
          active={routesOpen}
          onClick={wrap(() => onAction("routes"))}
        />
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
  onClick,
}: {
  icon: IconComp;
  label: string;
  expanded: boolean;
  active?: boolean;
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
      {active && !expanded && (
        <span className="absolute -right-0.5 top-1/2 h-6 w-0.5 -translate-y-1/2 rounded-full bg-cyan-300 shadow-[0_0_8px_rgba(34,211,238,0.8)]" />
      )}
    </button>
  );
}
