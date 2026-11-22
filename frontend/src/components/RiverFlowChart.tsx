import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { t } from "../lib/copy";
import { fechaCorta, numero } from "../lib/format";
import type { FlowSeries, River } from "../lib/types";
import { ChartCard, chartTheme } from "./chartTheme";

type Props = {
  river: River;
  series: FlowSeries | null;
  loading: boolean;
  error: string | null;
};

export default function RiverFlowChart({ river, series, loading, error }: Props) {
  const theme = chartTheme();
  const points = series?.points ?? [];
  const trend = computeTrend(points);

  return (
    <ChartCard
      title={`${t("caudal.titulo")} (${series?.unit ?? t("caudal.unidad")})`}
      loading={loading}
      error={error}
      pending={points.length === 0 ? t("caudal.pendiente_detalle") : null}
      footer={
        <>
          <span className="inline-flex items-center gap-1">
            <i className="inline-block w-4 border-t-2 border-ink" />
            {t("caudal.titulo")}
          </span>
          {trend && (
            <span className="inline-flex items-center gap-1">
              <i className="inline-block w-4 border-t-2 border-dashed border-text-muted" />
              {t("caudal.tendencia")}
            </span>
          )}
        </>
      }
    >
      <p className="mb-2 mt-0 text-small text-text-muted">
        {t("caudal.estacion", { nombre: river.station_name })} · {river.source}
        {series?.first_date && series.last_date && (
          <span className="tnum">
            {" · "}
            {fechaCorta(series.first_date)} – {fechaCorta(series.last_date)}
          </span>
        )}
      </p>
      <div className="h-[200px]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={points.map((p, i) => ({
              ...p,
              trend: trend ? trend.intercept + trend.slope * i : null,
            }))}
            margin={{ top: 4, right: 8, left: 0, bottom: 0 }}
          >
            <CartesianGrid stroke={theme.grid} vertical={false} />
            <XAxis
              dataKey="label"
              tick={theme.tick}
              tickLine={false}
              axisLine={{ stroke: theme.axis }}
              minTickGap={20}
            />
            <YAxis tick={theme.tick} tickLine={false} axisLine={false} width={40} />
            <Tooltip
              contentStyle={theme.tooltip}
              formatter={(value: number, name: string) => [
                typeof value === "number" ? `${numero(value, 2)} ${series?.unit ?? t("caudal.unidad")}` : value,
                name === "value" ? t("caudal.titulo") : t("caudal.tendencia"),
              ]}
            />
            <Line
              type="monotone"
              dataKey="value"
              stroke={theme.series}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
              connectNulls
            />
            {trend && (
              <Line
                type="linear"
                dataKey="trend"
                stroke={theme.reference}
                strokeWidth={1.5}
                strokeDasharray="4 4"
                dot={false}
                isAnimationActive={false}
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
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
