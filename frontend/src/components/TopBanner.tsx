import { useMemo, useState } from "react";
import { ChevronLeftIcon, ChevronRightIcon } from "../lib/icons";
import type { ObservationScene, PredictionScene } from "../lib/types";
import {
  WEATHER_HORIZONS,
  type WeatherHorizon,
  type WeatherManifest,
} from "../lib/weather";

type Scene = { date: string; isPrediction: boolean };

type Props = {
  observations: ObservationScene[];
  predictions: PredictionScene[];
  selectedDate: string | null;
  onDateChange: (date: string | null) => void;
  weatherManifest: WeatherManifest | null;
  weatherLoading: boolean;
  weatherHorizon: WeatherHorizon | null;
  onWeatherHorizonChange: (horizon: WeatherHorizon | null) => void;
};

export default function TopBanner({
  observations,
  predictions,
  selectedDate,
  onDateChange,
  weatherManifest,
  weatherLoading,
  weatherHorizon,
  onWeatherHorizonChange,
}: Props) {
  const scenes: Scene[] = useMemo(() => {
    const obs = observations.map((o) => ({ date: o.date, isPrediction: false }));
    const pred = predictions.map((p) => ({ date: p.date, isPrediction: true }));
    return [...obs, ...pred].sort((a, b) => a.date.localeCompare(b.date));
  }, [observations, predictions]);

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
        scenes={scenes}
        selectedDate={selectedDate}
        onChange={onDateChange}
      />

      <WeatherPills
        manifest={weatherManifest}
        loading={weatherLoading}
        selected={weatherHorizon}
        onChange={onWeatherHorizonChange}
      />

      <div className="ml-auto flex items-center gap-3">
        <SceneStatus
          observationCount={observations.length}
          predictionCount={predictions.length}
        />
      </div>
    </header>
  );
}

function DateNavigator({
  scenes,
  selectedDate,
  onChange,
}: {
  scenes: Scene[];
  selectedDate: string | null;
  onChange: (date: string | null) => void;
}) {
  const [open, setOpen] = useState(false);

  const predictionDates = useMemo(
    () => new Set(scenes.filter((s) => s.isPrediction).map((s) => s.date)),
    [scenes],
  );
  const availableDates = useMemo(
    () => new Set(scenes.map((s) => s.date)),
    [scenes],
  );

  const selectedIndex = scenes.findIndex((s) => s.date === selectedDate);
  const selected = selectedIndex >= 0 ? scenes[selectedIndex] : null;
  const isForecast = selected?.isPrediction ?? false;
  const formatted = selected ? formatDate(selected.date) : "Loading scenes";
  const atFirst = selectedIndex <= 0;
  const atLast = selectedIndex < 0 || selectedIndex >= scenes.length - 1;

  return (
    <div className="relative">
      <div className="flex items-center gap-1 rounded-full border border-white/10 bg-slate-900/60 p-1">
        <button
          onClick={() => onChange(scenes[selectedIndex - 1]?.date ?? null)}
          disabled={atFirst}
          className="flex h-8 w-8 items-center justify-center rounded-full text-slate-400 transition hover:bg-white/5 hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-slate-400"
          aria-label="Previous scene"
        >
          <ChevronLeftIcon className="h-4 w-4" />
        </button>
        <button
          onClick={() => setOpen((value) => !value)}
          className="flex min-w-[168px] items-center gap-2 rounded-full px-3 text-sm font-medium tabular-nums text-slate-100 transition hover:bg-white/5"
        >
          {isForecast && (
            <span className="rounded bg-amber-400/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-300">
              Forecast
            </span>
          )}
          {formatted}
        </button>
        <button
          onClick={() => onChange(scenes[selectedIndex + 1]?.date ?? null)}
          disabled={atLast}
          className="flex h-8 w-8 items-center justify-center rounded-full text-slate-400 transition hover:bg-white/5 hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:text-slate-400"
          aria-label="Next scene"
        >
          <ChevronRightIcon className="h-4 w-4" />
        </button>
      </div>

      {open && selected && (
        <SceneCalendar
          selectedDate={selected.date}
          availableDates={availableDates}
          predictionDates={predictionDates}
          onSelect={(date) => {
            onChange(date);
            setOpen(false);
          }}
        />
      )}
    </div>
  );
}

function WeatherPills({
  manifest,
  loading,
  selected,
  onChange,
}: {
  manifest: WeatherManifest | null;
  loading: boolean;
  selected: WeatherHorizon | null;
  onChange: (horizon: WeatherHorizon | null) => void;
}) {
  const model = manifest?.models.find((item) => item.id === "gfs");
  return (
    <div className="flex items-center gap-1 rounded-full border border-white/10 bg-slate-900/60 p-1">
      <span className="px-2 text-[10px] uppercase tracking-[0.16em] text-slate-500">
        {loading ? "Weather..." : model ? "GFS precip" : "Weather unavailable"}
      </span>
      {WEATHER_HORIZONS.map((horizon) => {
        const available = Boolean(
          model?.horizons[String(horizon)]?.precipitation_total.available,
        );
        return (
          <button
            key={horizon}
            onClick={() => onChange(selected === horizon ? null : horizon)}
            disabled={!available}
            aria-pressed={selected === horizon}
            title={
              available
                ? model?.horizons[String(horizon)]?.valid_at
                : "Forecast not generated yet"
            }
            className={`rounded-full px-3 py-1.5 text-[13px] font-medium tabular-nums transition disabled:cursor-not-allowed disabled:opacity-25 ${
              selected === horizon
                ? "bg-cyan-300 text-slate-950"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            {horizon === 120 ? "5d" : `${horizon}h`}
          </button>
        );
      })}
    </div>
  );
}

function SceneCalendar({
  selectedDate,
  availableDates,
  predictionDates,
  onSelect,
}: {
  selectedDate: string;
  availableDates: Set<string>;
  predictionDates: Set<string>;
  onSelect: (date: string) => void;
}) {
  const [visibleMonth, setVisibleMonth] = useState(() =>
    monthStart(parseDate(selectedDate)),
  );
  const days = calendarDays(visibleMonth);

  return (
    <div className="absolute left-0 top-12 w-[292px] rounded-xl border border-white/10 bg-[#081020]/95 p-3 shadow-[0_24px_60px_-20px_rgba(0,0,0,0.9)] backdrop-blur-xl">
      <div className="mb-2 flex items-center justify-between">
        <button
          onClick={() => setVisibleMonth(addMonths(visibleMonth, -1))}
          className="flex h-7 w-7 items-center justify-center rounded-full text-slate-400 transition hover:bg-white/5 hover:text-slate-100"
          aria-label="Previous month"
        >
          <ChevronLeftIcon className="h-4 w-4" />
        </button>
        <span className="text-sm font-medium text-slate-100">
          {visibleMonth.toLocaleDateString("en-GB", {
            month: "long",
            year: "numeric",
            timeZone: "UTC",
          })}
        </span>
        <button
          onClick={() => setVisibleMonth(addMonths(visibleMonth, 1))}
          className="flex h-7 w-7 items-center justify-center rounded-full text-slate-400 transition hover:bg-white/5 hover:text-slate-100"
          aria-label="Next month"
        >
          <ChevronRightIcon className="h-4 w-4" />
        </button>
      </div>

      <div className="grid grid-cols-7 gap-1 text-center text-[10px] uppercase tracking-[0.12em] text-slate-500">
        {["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"].map((day) => (
          <span key={day} className="py-1">
            {day}
          </span>
        ))}
      </div>
      <div className="mt-1 grid grid-cols-7 gap-1">
        {days.map((day) => {
          const key = isoDate(day);
          const available = availableDates.has(key);
          const isPrediction = predictionDates.has(key);
          const active = key === selectedDate;
          const inMonth = day.getUTCMonth() === visibleMonth.getUTCMonth();

          return (
            <button
              key={key}
              onClick={() => available && onSelect(key)}
              disabled={!available}
              className={`relative flex h-8 items-center justify-center rounded-md text-xs tabular-nums transition ${
                active
                  ? isPrediction
                    ? "bg-amber-400 text-slate-950"
                    : "bg-cyan-300 text-slate-950"
                  : available
                    ? isPrediction
                      ? "bg-amber-400/15 text-amber-100 hover:bg-amber-400/25"
                      : "bg-cyan-400/10 text-cyan-100 hover:bg-cyan-400/20"
                    : inMonth
                      ? "text-slate-600"
                      : "text-slate-700"
              }`}
            >
              {day.getUTCDate()}
              {available && !active && (
                <span
                  className={`absolute bottom-1 h-1 w-1 rounded-full ${
                    isPrediction ? "bg-amber-400" : "bg-cyan-300"
                  }`}
                />
              )}
            </button>
          );
        })}
      </div>

      <div className="mt-2 flex items-center gap-3 border-t border-white/5 pt-2 text-[10px] text-slate-500">
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-sm bg-cyan-400/30" />
          Observation
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-sm bg-amber-400/30" />
          Forecast
        </span>
      </div>
    </div>
  );
}

function SceneStatus({
  observationCount,
  predictionCount,
}: {
  observationCount: number;
  predictionCount: number;
}) {
  return (
    <div className="hidden lg:flex items-center gap-2.5 rounded-full border border-white/10 bg-slate-900/60 px-3.5 py-2">
      <span className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
      </span>
      <span className="text-[11px] uppercase tracking-[0.22em] text-slate-400">
        Scenes
      </span>
      <span className="text-xs text-slate-300 tabular-nums">{observationCount}</span>
      {predictionCount > 0 && (
        <>
          <span className="text-slate-600">·</span>
          <span className="text-[11px] uppercase tracking-[0.22em] text-amber-500">
            Forecast
          </span>
          <span className="text-xs text-amber-300 tabular-nums">{predictionCount}</span>
        </>
      )}
    </div>
  );
}

function formatDate(value: string) {
  return parseDate(value).toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

function parseDate(value: string) {
  return new Date(`${value}T00:00:00Z`);
}

function isoDate(value: Date) {
  return value.toISOString().slice(0, 10);
}

function monthStart(value: Date) {
  return new Date(Date.UTC(value.getUTCFullYear(), value.getUTCMonth(), 1));
}

function addMonths(value: Date, months: number) {
  return new Date(Date.UTC(value.getUTCFullYear(), value.getUTCMonth() + months, 1));
}

function calendarDays(month: Date) {
  const start = monthStart(month);
  const weekday = (start.getUTCDay() + 6) % 7;
  const first = new Date(start);
  first.setUTCDate(start.getUTCDate() - weekday);
  return Array.from({ length: 42 }, (_, index) => {
    const day = new Date(first);
    day.setUTCDate(first.getUTCDate() + index);
    return day;
  });
}
