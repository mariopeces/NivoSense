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

const AVAILABLE_YEARS = [2024, 2025, 2026];

type Props = {
  basinName: string;
  data: CoverageSeriesPoint[];
  loading: boolean;
  error: string | null;
  onClose: () => void;
  hydrologicalYear: number;
  onYearChange: (year: number) => void;
};

export default function BasinChart({
  basinName,
  data,
  loading,
  error,
  onClose,
  hydrologicalYear,
  onYearChange,
}: Props) {
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
        ) : data.length === 0 ? (
          <StatusState title="No observations for this basin" />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={data}
              margin={{ top: 4, right: 12, left: 0, bottom: 0 }}
            >
              <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
              <XAxis
                dataKey="label"
                tick={{ fill: "#94a3b8", fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: "rgba(255,255,255,0.08)" }}
                minTickGap={18}
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
                dataKey="observed"
                stroke="#67e8f9"
                strokeWidth={2}
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
    <div className="flex items-center gap-3 text-[11px] text-slate-400">
      <span className="flex items-center gap-1.5">
        <span className="block h-0.5 w-4 rounded-full bg-cyan-300" />
        Snow
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
