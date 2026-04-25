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
import type { CoverageSeriesPoint } from "../lib/types";

type Props = {
  basinName: string;
  data: CoverageSeriesPoint[];
  onClose: () => void;
};

export default function BasinChart({ basinName, data, onClose }: Props) {
  return (
    <div className="pointer-events-auto absolute bottom-4 left-20 z-20 w-[420px] rounded-2xl border border-white/10 bg-slate-950/85 backdrop-blur-xl shadow-[0_30px_80px_-20px_rgba(0,0,0,0.85)]">
      <div className="flex items-start justify-between gap-3 px-4 pt-3.5">
        <div>
          <span className="text-[10px] uppercase tracking-[0.22em] text-slate-500">
            Basin coverage
          </span>
          <h3 className="mt-0.5 text-sm font-semibold text-white">{basinName}</h3>
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

      <div className="h-[180px] px-1 pb-1 pt-3">
        {data.length === 0 ? (
          <EmptyState />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={data}
              margin={{ top: 4, right: 12, left: 0, bottom: 0 }}
            >
              <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
              <XAxis
                dataKey="month"
                tick={{ fill: "#64748b", fontSize: 10 }}
                tickLine={false}
                axisLine={{ stroke: "rgba(255,255,255,0.08)" }}
              />
              <YAxis
                tick={{ fill: "#64748b", fontSize: 10 }}
                tickLine={false}
                axisLine={false}
                domain={[0, 100]}
                tickFormatter={(v) => `${v}%`}
                width={36}
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
                dataKey="average"
                stroke="#94a3b8"
                strokeWidth={1.5}
                strokeDasharray="3 3"
                dot={false}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="observed"
                stroke="#67e8f9"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="forecast"
                stroke="#67e8f9"
                strokeWidth={2}
                strokeDasharray="5 3"
                dot={false}
                isAnimationActive={false}
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
    <div className="flex items-center gap-3 text-[10px] text-slate-400">
      <span className="flex items-center gap-1.5">
        <span className="block h-px w-4 border-t border-dashed border-slate-400" />
        Avg.
      </span>
      <span className="flex items-center gap-1.5">
        <span className="block h-0.5 w-4 rounded-full bg-cyan-300" />
        2026
      </span>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center px-4 text-center">
      <p className="text-xs text-slate-400">No coverage data yet</p>
      <p className="mt-1 text-[10px] leading-relaxed text-slate-600">
        Series for the selected basin will appear here once the backend
        publishes <code className="text-slate-400">/basins/&#123;id&#125;/stats</code>.
      </p>
    </div>
  );
}
