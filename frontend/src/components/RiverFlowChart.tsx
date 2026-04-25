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
import type { FlowSeries, River } from "../lib/types";

type Props = {
  river: River;
  series: FlowSeries | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
};

export default function RiverFlowChart({
  river,
  series,
  loading,
  error,
  onClose,
}: Props) {
  const points = series?.points ?? [];
  const trend = computeTrend(points);

  return (
    <div className="pointer-events-auto absolute bottom-4 left-[280px] z-20 w-[460px] rounded-2xl border border-white/10 bg-[#081020]/85 backdrop-blur-xl shadow-[0_30px_80px_-20px_rgba(0,0,0,0.85)]">
      <div className="flex items-start justify-between gap-3 px-5 pt-4">
        <div>
          <span className="text-[11px] uppercase tracking-[0.22em] text-slate-400">
            River flow · {river.station_name}
          </span>
          <h3 className="mt-1 text-base font-semibold text-white">
            {river.name}
          </h3>
          {series && (
            <p className="mt-0.5 text-[11px] text-slate-500">
              {series.source} · {series.unit}
              {series.first_date && series.last_date && (
                <>
                  {" · "}
                  {series.first_date} — {series.last_date}
                </>
              )}
            </p>
          )}
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
          <StatusState title="Loading flow series…" />
        ) : error ? (
          <StatusState title={error} />
        ) : points.length === 0 ? (
          <StatusState title="No flow data for this river" />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={points.map((p, i) => ({
                ...p,
                trend: trend ? trend.intercept + trend.slope * i : null,
              }))}
              margin={{ top: 4, right: 12, left: 0, bottom: 0 }}
            >
              <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
              <XAxis
                dataKey="label"
                tick={{ fill: "#94a3b8", fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: "rgba(255,255,255,0.08)" }}
                minTickGap={20}
              />
              <YAxis
                tick={{ fill: "#94a3b8", fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                width={40}
                tickFormatter={(v) => `${v}`}
              />
              <Tooltip
                contentStyle={{
                  background: "rgba(2, 6, 23, 0.95)",
                  border: "1px solid rgba(255,255,255,0.1)",
                  borderRadius: "8px",
                  fontSize: 11,
                }}
                labelStyle={{ color: "#cbd5e1" }}
                formatter={(value: number, name: string) => [
                  typeof value === "number" ? value.toFixed(2) : value,
                  name === "value" ? `${series?.unit ?? "m³/s"}` : name,
                ]}
              />
              <Line
                type="monotone"
                dataKey="value"
                stroke="#67e8f9"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
              {trend && (
                <Line
                  type="linear"
                  dataKey="trend"
                  stroke="#a5f3fc"
                  strokeWidth={1.5}
                  strokeDasharray="4 4"
                  dot={false}
                  isAnimationActive={false}
                />
              )}
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
        Flow
      </span>
      <span className="flex items-center gap-1.5">
        <span className="block h-px w-4 border-t border-dashed border-cyan-200" />
        Trend
      </span>
    </div>
  );
}

function StatusState({ title }: { title: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-4 text-center">
      <p className="text-sm text-slate-300">{title}</p>
    </div>
  );
}

function computeTrend(points: { value: number | null }[]): {
  slope: number;
  intercept: number;
} | null {
  const valid = points
    .map((p, i) => ({ x: i, y: p.value }))
    .filter((p): p is { x: number; y: number } => typeof p.y === "number");
  if (valid.length < 2) return null;

  const n = valid.length;
  const sumX = valid.reduce((acc, p) => acc + p.x, 0);
  const sumY = valid.reduce((acc, p) => acc + p.y, 0);
  const sumXY = valid.reduce((acc, p) => acc + p.x * p.y, 0);
  const sumXX = valid.reduce((acc, p) => acc + p.x * p.x, 0);

  const denominator = n * sumXX - sumX * sumX;
  if (denominator === 0) return null;

  const slope = (n * sumXY - sumX * sumY) / denominator;
  const intercept = (sumY - slope * sumX) / n;

  return { slope, intercept };
}
