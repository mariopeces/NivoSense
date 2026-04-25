import { LogoMark, ChevronLeftIcon, ChevronRightIcon } from "../lib/icons";
import { HORIZONS, type HorizonId } from "../lib/horizons";

type Props = {
  date: Date;
  onDateChange: (date: Date) => void;
  horizon: HorizonId | null;
  onHorizonChange: (id: HorizonId | null) => void;
};

export default function TopBanner({
  date,
  onDateChange,
  horizon,
  onHorizonChange,
}: Props) {
  return (
    <header className="pointer-events-auto absolute inset-x-0 top-0 z-30 flex h-14 items-center gap-6 border-b border-white/5 bg-slate-950/80 px-5 backdrop-blur-xl">
      <div className="flex items-center gap-2.5">
        <Logo />
        <span className="text-base font-semibold tracking-tight text-white">
          NivoSense
        </span>
      </div>

      <div className="ml-2 h-6 w-px bg-white/10" />

      <DateNavigator date={date} onChange={onDateChange} />

      <HorizonPills value={horizon} onChange={onHorizonChange} />

      <div className="ml-auto flex items-center gap-3">
        <ModelStatus />
      </div>
    </header>
  );
}

function Logo() {
  return (
    <div className="relative flex h-8 w-8 items-center justify-center rounded-lg border border-cyan-300/20 bg-gradient-to-br from-cyan-500/20 via-sky-600/10 to-slate-900/0 shadow-[0_0_20px_-6px_rgba(34,211,238,0.6)]">
      <LogoMark className="h-4.5 w-4.5 text-cyan-300" />
    </div>
  );
}

function DateNavigator({
  date,
  onChange,
}: {
  date: Date;
  onChange: (d: Date) => void;
}) {
  const formatted = date.toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  });

  const step = (days: number) => {
    const next = new Date(date);
    next.setDate(next.getDate() + days);
    onChange(next);
  };

  return (
    <div className="flex items-center gap-1 rounded-full border border-white/10 bg-slate-900/60 p-1">
      <button
        onClick={() => step(-1)}
        className="flex h-7 w-7 items-center justify-center rounded-full text-slate-400 transition hover:bg-white/5 hover:text-slate-100"
        aria-label="Previous day"
      >
        <ChevronLeftIcon className="h-3.5 w-3.5" />
      </button>
      <span className="px-2 text-xs font-medium tabular-nums text-slate-200">
        {formatted}
      </span>
      <button
        onClick={() => step(1)}
        className="flex h-7 w-7 items-center justify-center rounded-full text-slate-400 transition hover:bg-white/5 hover:text-slate-100"
        aria-label="Next day"
      >
        <ChevronRightIcon className="h-3.5 w-3.5" />
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
            className={`rounded-full px-3 py-1 text-[11px] font-medium tabular-nums transition ${
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
    <div className="hidden lg:flex items-center gap-2 rounded-full border border-white/10 bg-slate-900/60 px-3 py-1.5">
      <span className="relative flex h-1.5 w-1.5">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
      </span>
      <span className="text-[10px] uppercase tracking-[0.22em] text-slate-400">
        Last run
      </span>
      <span className="text-[11px] text-slate-300 tabular-nums">—</span>
    </div>
  );
}
