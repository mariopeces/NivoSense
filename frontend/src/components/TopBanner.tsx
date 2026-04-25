import { ChevronLeftIcon, ChevronRightIcon } from "../lib/icons";
import type { ObservationScene } from "../lib/types";

type Props = {
  observations: ObservationScene[];
  selectedDate: string | null;
  onDateChange: (date: string | null) => void;
};

export default function TopBanner({
  observations,
  selectedDate,
  onDateChange,
}: Props) {
  return (
    <header className="pointer-events-auto absolute inset-x-0 top-0 z-30 flex h-16 items-center gap-5 border-b border-white/5 bg-[#081020]/90 px-6 backdrop-blur-md">
      <a
        href={import.meta.env.BASE_URL}
        className="flex items-center"
        aria-label="NivoSense home"
      >
        <img
          src={`${import.meta.env.BASE_URL}logo.png`}
          alt="NivoSense"
          className="h-12 w-auto select-none"
          draggable={false}
        />
      </a>

      <div className="ml-2 h-6 w-px bg-white/10" />

      <DateNavigator
        observations={observations}
        selectedDate={selectedDate}
        onChange={onDateChange}
      />

      <ObservationTicks
        observations={observations}
        selectedDate={selectedDate}
        onChange={onDateChange}
      />

      <div className="ml-auto flex items-center gap-3">
        <SceneStatus count={observations.length} />
      </div>
    </header>
  );
}

function DateNavigator({
  observations,
  selectedDate,
  onChange,
}: {
  observations: ObservationScene[];
  selectedDate: string | null;
  onChange: (date: string | null) => void;
}) {
  const selectedIndex = observations.findIndex(
    (item) => item.date === selectedDate,
  );
  const selected = selectedIndex >= 0 ? observations[selectedIndex] : null;
  const formatted = selected ? formatDate(selected.date) : "Loading scenes";
  const atFirst = selectedIndex <= 0;
  const atLast = selectedIndex < 0 || selectedIndex >= observations.length - 1;

  return (
    <div className="flex items-center gap-1 rounded-full border border-white/10 bg-slate-900/60 p-1">
      <button
        onClick={() => onChange(observations[selectedIndex - 1]?.date ?? null)}
        disabled={atFirst}
        className="flex h-8 w-8 items-center justify-center rounded-full text-slate-400 transition hover:bg-white/5 hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-slate-400"
        aria-label="Previous observation"
      >
        <ChevronLeftIcon className="h-4 w-4" />
      </button>
      <span className="px-3 text-sm font-medium tabular-nums text-slate-100">
        {formatted}
      </span>
      <button
        onClick={() => onChange(observations[selectedIndex + 1]?.date ?? null)}
        disabled={atLast}
        className="flex h-8 w-8 items-center justify-center rounded-full text-slate-400 transition hover:bg-white/5 hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-slate-400"
        aria-label="Next observation"
      >
        <ChevronRightIcon className="h-4 w-4" />
      </button>
    </div>
  );
}

function ObservationTicks({
  observations,
  selectedDate,
  onChange,
}: {
  observations: ObservationScene[];
  selectedDate: string | null;
  onChange: (date: string | null) => void;
}) {
  const selectedIndex = observations.findIndex(
    (item) => item.date === selectedDate,
  );

  return (
    <div className="hidden min-w-0 flex-1 items-center gap-3 xl:flex">
      <span className="shrink-0 text-[11px] uppercase tracking-[0.22em] text-slate-400">
        2024 scenes
      </span>
      <input
        type="range"
        min={0}
        max={Math.max(observations.length - 1, 0)}
        value={Math.max(selectedIndex, 0)}
        disabled={observations.length === 0}
        onChange={(event) => {
          const index = Number(event.currentTarget.value);
          onChange(observations[index]?.date ?? null);
        }}
        className="h-1 min-w-0 flex-1 accent-cyan-300"
      />
    </div>
  );
}

function SceneStatus({ count }: { count: number }) {
  return (
    <div className="hidden lg:flex items-center gap-2.5 rounded-full border border-white/10 bg-slate-900/60 px-3.5 py-2">
      <span className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
      </span>
      <span className="text-[11px] uppercase tracking-[0.22em] text-slate-400">
        Scenes
      </span>
      <span className="text-xs text-slate-300 tabular-nums">{count}</span>
    </div>
  );
}

function formatDate(value: string) {
  return new Date(`${value}T00:00:00Z`).toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}
