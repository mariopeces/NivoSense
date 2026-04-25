import { ChevronLeftIcon, ChevronRightIcon } from "../lib/icons";
import {
  HORIZONS,
  horizonToDate,
  nextHorizon,
  previousHorizon,
  isFirstHorizon,
  isLastHorizon,
  type HorizonId,
} from "../lib/horizons";

type Props = {
  horizon: HorizonId | null;
  onHorizonChange: (id: HorizonId | null) => void;
};

export default function TopBanner({ horizon, onHorizonChange }: Props) {
  return (
    <header className="pointer-events-auto absolute inset-x-0 top-0 z-30 flex h-16 items-center gap-6 border-b border-white/5 bg-[#081020]/90 px-6 backdrop-blur-md">
      <a href="/" className="flex items-center" aria-label="NivoSense home">
        <img
          src="/logo.png"
          alt="NivoSense"
          className="h-12 w-auto select-none"
          draggable={false}
        />
      </a>

      <div className="ml-2 h-6 w-px bg-white/10" />

      <DateNavigator horizon={horizon} onChange={onHorizonChange} />

      <HorizonPills value={horizon} onChange={onHorizonChange} />

      <div className="ml-auto flex items-center gap-3">
        <ModelStatus />
      </div>
    </header>
  );
}

function DateNavigator({
  horizon,
  onChange,
}: {
  horizon: HorizonId | null;
  onChange: (h: HorizonId | null) => void;
}) {
  const date = horizonToDate(horizon);
  const formatted = date.toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  });

  const atFirst = isFirstHorizon(horizon);
  const atLast = isLastHorizon(horizon);

  return (
    <div className="flex items-center gap-1 rounded-full border border-white/10 bg-slate-900/60 p-1">
      <button
        onClick={() => onChange(previousHorizon(horizon))}
        disabled={atFirst}
        className="flex h-8 w-8 items-center justify-center rounded-full text-slate-400 transition hover:bg-white/5 hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-slate-400"
        aria-label="Previous horizon"
      >
        <ChevronLeftIcon className="h-4 w-4" />
      </button>
      <span className="px-3 text-sm font-medium tabular-nums text-slate-100">
        {formatted}
      </span>
      <button
        onClick={() => onChange(nextHorizon(horizon))}
        disabled={atLast}
        className="flex h-8 w-8 items-center justify-center rounded-full text-slate-400 transition hover:bg-white/5 hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-slate-400"
        aria-label="Next horizon"
      >
        <ChevronRightIcon className="h-4 w-4" />
      </button>
    </div>
  );
}

function HorizonPills({
  value,
  onChange,
}: {
  value: HorizonId | null;
  onChange: (id: HorizonId | null) => void;
}) {
  return (
    <div className="flex items-center gap-1 rounded-full border border-white/10 bg-slate-900/60 p-1">
      {HORIZONS.map((h) => {
        const active = h.id === value;
        return (
          <button
            key={h.id}
            onClick={() => onChange(active ? null : h.id)}
            className={`rounded-full px-3.5 py-1.5 text-[13px] font-medium tabular-nums transition ${
              active
                ? "bg-cyan-400/15 text-cyan-200 shadow-[inset_0_0_0_1px_rgba(34,211,238,0.4)]"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            {h.short}
          </button>
        );
      })}
    </div>
  );
}

function ModelStatus() {
  return (
    <div className="hidden lg:flex items-center gap-2.5 rounded-full border border-white/10 bg-slate-900/60 px-3.5 py-2">
      <span className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
      </span>
      <span className="text-[11px] uppercase tracking-[0.22em] text-slate-400">
        Last run
      </span>
      <span className="text-xs text-slate-300 tabular-nums">—</span>
    </div>
  );
}
