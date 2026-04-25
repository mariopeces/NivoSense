import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { CloseIcon } from "../lib/icons";
import type { BasinSeries } from "../lib/types";

type Props = {
  basinName: string;
  series: BasinSeries | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
};

export default function BasinChart({
  basinName,
  series,
  loading,
  error,
  onClose,
}: Props) {
  const observedData =
    series?.points.map((point) => ({
      ...point,
      value: point.observed,
    })) ?? [];
  const averageData =
    series?.average_points.map((point) => ({
      ...point,
      value: point.average,
    })) ?? [];
  const hasData = observedData.length > 0 || averageData.length > 0;

  return (
    <div className="pointer-events-auto absolute bottom-4 left-[280px] z-20 w-[460px] rounded-2xl border border-white/10 bg-[#081020]/85 backdrop-blur-xl shadow-[0_30px_80px_-20px_rgba(0,0,0,0.85)]">
      <div className="flex items-start justify-between gap-3 px-5 pt-4">
        <div>
          <span className="text-[11px] uppercase tracking-[0.22em] text-slate-400">
            Hydrological year {series?.hydrological_year ?? "2023-2024"}
          </span>
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
            <LineChart
              data={averageData}
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
                tick={{ fill: "#94a3b8", fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                domain={[0, 100]}
                tickFormatter={(v) => `${v}%`}
                width={40}
              />
              <Tooltip
                contentStyle={{
                  background: "rgba(2, 6, 23, 0.95)",
                  border: "1px solid rgba(255,255,255,0.1)",
                  borderRadius: "8px",
                  fontSize: 11,
                }}
                labelStyle={{ color: "#cbd5e1" }}
              />
              <Line
                type="monotone"
                dataKey="value"
                name="Historical avg."
                stroke="#94a3b8"
                strokeWidth={1.5}
                strokeDasharray="4 4"
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
              <Line
                data={observedData}
                type="monotone"
                dataKey="value"
                name={series?.hydrological_year ?? "Selected year"}
                stroke="#67e8f9"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
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

function StatusState({ title }: { title: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-4 text-center">
      <p className="text-sm text-slate-300">{title}</p>
    </div>
  );
}
