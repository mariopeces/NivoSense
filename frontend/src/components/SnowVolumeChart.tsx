import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { CloseIcon } from "../lib/icons";
import type {
  BasinVolumeSeries,
  SnowModelBasin,
  SnowModelManifest,
} from "../lib/snowModel";

type Props = {
  basin: SnowModelBasin | null;
  basinName: string;
  manifest: SnowModelManifest | null;
  series: BasinVolumeSeries | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
};

function formatDate(value: string) {
  return new Date(`${value}T00:00:00Z`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

export default function SnowVolumeChart({
  basin,
  basinName,
  manifest,
  series,
  loading,
  error,
  onClose,
}: Props) {
  const model = manifest?.model;
  const calibration = model?.calibration;
  const data =
    series?.dates.map((date, index) => ({
      date,
      band: [series.swe_hm3.p10[index], series.swe_hm3.p90[index]],
      median: series.swe_hm3.p50[index],
    })) ?? [];
  const latest = basin?.latest;
  const message = loading
    ? "Loading snow volume"
    : error
      ? error
      : model && model.status !== "available"
        ? (model.reasons[0] ?? "Snow model not available")
        : data.length === 0
          ? "No snow volume for this basin yet"
          : null;

  return (
    <div className="pointer-events-auto absolute bottom-4 left-[280px] z-20 w-[460px] rounded-2xl border border-white/10 bg-[#081020]/85 backdrop-blur-xl shadow-[0_30px_80px_-20px_rgba(0,0,0,0.85)]">
      <div className="flex items-start justify-between gap-3 px-5 pt-4">
        <div>
          <span className="text-[11px] uppercase tracking-[0.2em] text-slate-500">
            Snow water volume
          </span>
          <h3 className="mt-0.5 text-base font-semibold text-white">{basinName}</h3>
          {basin && (
            <p className="text-[11px] text-slate-500">{basin.area_km2} km2 modelled</p>
          )}
        </div>
        <button
          onClick={onClose}
          className="flex h-6 w-6 items-center justify-center rounded-full text-slate-400 transition hover:bg-white/5 hover:text-slate-100"
          aria-label="Close"
        >
          <CloseIcon className="h-3.5 w-3.5" />
        </button>
      </div>

      {latest && !message && (
        <div className="mt-2 flex gap-6 px-5">
          <div>
            <div className="text-xl font-semibold tabular-nums text-cyan-200">
              {latest.swe_hm3.p50.toFixed(1)}
              <span className="ml-1 text-xs font-normal text-slate-400">hm3</span>
            </div>
            <div className="text-[11px] tabular-nums text-slate-500">
              {latest.swe_hm3.p10.toFixed(1)} to {latest.swe_hm3.p90.toFixed(1)} (p10 to p90)
            </div>
          </div>
          <div>
            <div className="text-xl font-semibold tabular-nums text-slate-100">
              {latest.snow_area_km2.p50.toFixed(1)}
              <span className="ml-1 text-xs font-normal text-slate-400">km2</span>
            </div>
            <div className="text-[11px] text-slate-500">snow covered on {formatDate(latest.date)}</div>
          </div>
        </div>
      )}

      <div className="h-[170px] px-2 pb-1 pt-3">
        {message ? (
          <div className="flex h-full items-center justify-center px-6 text-center text-xs text-slate-400">
            {message}
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={data} margin={{ top: 4, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
              <XAxis
                dataKey="date"
                tick={{ fill: "#94a3b8", fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: "rgba(255,255,255,0.08)" }}
                minTickGap={36}
                tickFormatter={formatDate}
              />
              <YAxis
                tick={{ fill: "#94a3b8", fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                width={40}
                tickFormatter={(value) => `${value}`}
              />
              <Tooltip
                contentStyle={{
                  background: "#081020",
                  border: "1px solid rgba(255,255,255,0.1)",
                  fontSize: 12,
                }}
                labelFormatter={(value) => formatDate(String(value))}
                formatter={(value, name) =>
                  Array.isArray(value)
                    ? [`${Number(value[0]).toFixed(1)} to ${Number(value[1]).toFixed(1)} hm3`, "p10 to p90"]
                    : [`${Number(value).toFixed(1)} hm3`, String(name)]
                }
              />
              <Area
                dataKey="band"
                name="p10 to p90"
                stroke="none"
                fill="#67e8f9"
                fillOpacity={0.22}
                isAnimationActive={false}
              />
              <Line
                dataKey="median"
                name="Median"
                stroke="#67e8f9"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>

      {calibration && (
        <p className="px-5 pb-3 text-[10px] leading-snug text-slate-500">
          Weighted ensemble of {model?.members ?? "?"} members, forced by{" "}
          {manifest?.forcing?.model} ({manifest?.forcing?.provider}). Held-out snow-cover F1{" "}
          {calibration.metrics.posterior.f1.toFixed(2)} against Sentinel-2 at 10 m.{" "}
          <span className="text-amber-300/80">
            Volume and depth magnitudes are not verified against in-situ measurements.
          </span>
        </p>
      )}
    </div>
  );
}
