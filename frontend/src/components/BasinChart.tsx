import {
  ComposedChart,
  Line,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { CloseIcon } from "../lib/icons";
import type { BasinSeries } from "../lib/types";

const AVAILABLE_YEARS = [2024, 2025, 2026];

type Props = {
  basinName: string;
  series: BasinSeries | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
  hydrologicalYear: number;
  onYearChange: (year: number) => void;
};

type ChartPoint = {
  hydro_day: number;
  date?: string;
  label: string;
  observed?: number | null;
  average?: number | null;
  quality?: number | null;
  masked?: number | null;
};

export default function BasinChart({
  basinName,
  series,
  loading,
  error,
  onClose,
  hydrologicalYear,
  onYearChange,
}: Props) {
  const chartData = buildChartData(series);
  const hasData = chartData.length > 0;

  return (
    <div className="pointer-events-auto absolute bottom-4 left-[280px] z-20 w-[460px] rounded-2xl border border-white/10 bg-[#081020]/85 backdrop-blur-xl shadow-[0_30px_80px_-20px_rgba(0,0,0,0.85)]">
      <div className="flex items-start justify-between gap-3 px-5 pt-4">
        <div>
          <div className="flex items-center gap-1">
            {AVAILABLE_YEARS.map((y) => (
              <button
                key={y}
                onClick={() => onYearChange(y)}
                className={`rounded px-2 py-0.5 text-[11px] font-medium transition ${
                  hydrologicalYear === y
                    ? "bg-cyan-400/20 text-cyan-300"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {y - 1}/{String(y).slice(2)}
              </button>
            ))}
          </div>
          <h3 className="mt-1 text-base font-semibold text-white">{basinName}</h3>
        </div>
        <div className="flex items-center gap-3">
          <Legend />
          <button
            onClick={onClose}
            className="flex h-6 w-6 items-center justify-center rounded-full text-slate-400 transition hover:bg-white/5 hover:text-slate-100"
            aria-label="Close"
          >
            <CloseIcon className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div className="h-[200px] px-2 pb-2 pt-3">
        {loading ? (
          <StatusState title="Loading snow evolution" />
        ) : error ? (
          <StatusState title={error} />
        ) : !hasData ? (
          <StatusState title="No observations for this basin" />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart
              data={chartData}
              margin={{ top: 4, right: 12, left: 0, bottom: 0 }}
            >
              <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
              <XAxis
                dataKey="hydro_day"
                type="number"
                domain={[0, 244]}
                tick={{ fill: "#94a3b8", fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: "rgba(255,255,255,0.08)" }}
                minTickGap={18}
                tickFormatter={formatHydroDay}
              />
              <YAxis
                yAxisId="snow"
                tick={{ fill: "#94a3b8", fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                domain={[0, 100]}
                tickFormatter={(v) => `${v}%`}
                width={40}
              />
              <YAxis yAxisId="quality" domain={[0, 100]} hide />
              <Tooltip content={<SnowTooltip />} />
              <Bar
                yAxisId="quality"
                dataKey="quality"
                name="Valid data"
                fill="#38bdf8"
                opacity={0.12}
                isAnimationActive={false}
              />
              <Line
                yAxisId="snow"
                type="monotone"
                dataKey="average"
                name="Historical avg."
                stroke="#94a3b8"
                strokeWidth={1.5}
                strokeDasharray="4 4"
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
              <Line
                yAxisId="snow"
                type="monotone"
                dataKey="observed"
                name={series?.hydrological_year ?? "Selected year"}
                stroke="#67e8f9"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}

function buildChartData(series: BasinSeries | null): ChartPoint[] {
  const byDay = new Map<number, ChartPoint>();

  for (const point of series?.average_points ?? []) {
    byDay.set(point.hydro_day, {
      hydro_day: point.hydro_day,
      label: point.label,
      average: point.average,
    });
  }

  for (const point of series?.points ?? []) {
    const current = byDay.get(point.hydro_day);
    byDay.set(point.hydro_day, {
      hydro_day: point.hydro_day,
      label: point.label,
      date: point.date,
      average: current?.average,
      observed: point.observed,
      quality: point.data_coverage_pct,
      masked:
        point.data_coverage_pct == null ? null : 100 - point.data_coverage_pct,
    });
  }

  return [...byDay.values()].sort((a, b) => a.hydro_day - b.hydro_day);
}

function SnowTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{
    name?: string;
    value?: number | null;
    color?: string;
    payload: ChartPoint;
  }>;
}) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  const title = point.date ? formatTooltipDate(point.date) : point.label;

  return (
    <div className="rounded-lg border border-white/10 bg-slate-950/95 px-3 py-2 text-[11px] shadow-xl">
      <p className="mb-1 font-medium text-slate-200">{title}</p>
      {payload
        .filter((entry) => entry.value != null)
        .map((entry) => (
          <p
            key={entry.name}
            className="tabular-nums"
            style={{ color: entry.color }}
          >
            {entry.name}: {Number(entry.value).toFixed(2)}%
          </p>
        ))}
      {point.masked != null && (
        <p className="mt-1 tabular-nums text-slate-400">
          Masked/cloud: {point.masked.toFixed(2)}%
        </p>
      )}
    </div>
  );
}

function Legend() {
  return (
    <div className="flex items-center gap-3 text-[11px] text-slate-400">
      <span className="flex items-center gap-1.5">
        <span className="block h-0.5 w-4 rounded-full bg-cyan-300" />
        2024
      </span>
      <span className="flex items-center gap-1.5">
        <span className="block h-px w-4 border-t border-dashed border-slate-400" />
        Avg.
      </span>
      <span className="flex items-center gap-1.5">
        <span className="block h-2 w-3 rounded-sm bg-sky-400/25" />
        Valid
      </span>
    </div>
  );
}

function formatHydroDay(value: number) {
  const ticks = [
    { day: 0, label: "Oct" },
    { day: 31, label: "Nov" },
    { day: 61, label: "Dec" },
    { day: 92, label: "Jan" },
    { day: 123, label: "Feb" },
    { day: 151, label: "Mar" },
    { day: 182, label: "Apr" },
    { day: 212, label: "May" },
    { day: 243, label: "Jun" },
  ];
  return ticks.reduce((best, tick) =>
    Math.abs(tick.day - value) < Math.abs(best.day - value) ? tick : best,
  ).label;
}

function formatTooltipDate(value: string) {
  return new Date(`${value}T00:00:00Z`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

function StatusState({ title }: { title: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-4 text-center">
      <p className="text-sm text-slate-300">{title}</p>
    </div>
  );
}
