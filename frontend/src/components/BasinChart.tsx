import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { t } from "../lib/copy";
import { fechaCorta, numero } from "../lib/format";
import type { BasinSeries } from "../lib/types";
import { ChartCard, chartTheme } from "./chartTheme";

const AVAILABLE_YEARS = [2024, 2025, 2026];

type Props = {
  series: BasinSeries | null;
  loading: boolean;
  error: string | null;
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
};

const MONTH_TICKS = [
  { day: 0, label: "oct" },
  { day: 31, label: "nov" },
  { day: 61, label: "dic" },
  { day: 92, label: "ene" },
  { day: 123, label: "feb" },
  { day: 151, label: "mar" },
  { day: 182, label: "abr" },
  { day: 212, label: "may" },
  { day: 243, label: "jun" },
];

export default function BasinChart({ series, loading, error, hydrologicalYear, onYearChange }: Props) {
  const theme = chartTheme();
  const chartData = buildChartData(series);

  return (
    <>
      <div className="mb-2 flex flex-wrap gap-1" role="group" aria-label={t("cuenca.temporada")}>
        {AVAILABLE_YEARS.map((year) => (
          <button
            key={year}
            type="button"
            aria-pressed={hydrologicalYear === year}
            onClick={() => onYearChange(year)}
            className={`tnum rounded-md border px-2 py-1 text-small font-medium ${
              hydrologicalYear === year ? "border-ink bg-ink text-on-ink-strong" : "border-line hover:bg-panel-soft"
            }`}
          >
            {year - 1}-{String(year).slice(2)}
          </button>
        ))}
      </div>
      <ChartCard
        title={t("cuenca.grafico_titulo_nieve_pct")}
        loading={loading}
        error={error}
        pending={chartData.length === 0 ? t("cuenca.pendiente_nieve_area") : null}
        footer={
          <>
            <span className="inline-flex items-center gap-1">
              <i className="inline-block w-4 border-t-2 border-ink" />
              {t("cuenca.esta_temporada")}
            </span>
            <span className="inline-flex items-center gap-1">
              <i className="inline-block w-4 border-t-2 border-dashed border-text-muted" />
              {t("cuenca.media_historica")}
            </span>
            <span className="inline-flex items-center gap-1">
              <i className="inline-block h-2 w-3 rounded-sm bg-panel-soft ring-1 ring-line-strong" />
              {t("cuenca.datos_validos")}
            </span>
          </>
        }
      >
        <div className="h-[200px]">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke={theme.grid} vertical={false} />
              <XAxis
                dataKey="hydro_day"
                type="number"
                domain={[0, 244]}
                ticks={MONTH_TICKS.map((tick) => tick.day)}
                tick={theme.tick}
                tickLine={false}
                axisLine={{ stroke: theme.axis }}
                tickFormatter={(day) => MONTH_TICKS.find((tick) => tick.day === day)?.label ?? ""}
              />
              <YAxis
                yAxisId="snow"
                tick={theme.tick}
                tickLine={false}
                axisLine={false}
                domain={[0, 100]}
                tickFormatter={(v) => `${v} %`}
                width={44}
              />
              <YAxis yAxisId="quality" domain={[0, 100]} hide />
              <Tooltip
                contentStyle={theme.tooltip}
                labelFormatter={(_, payload) => {
                  const point = payload?.[0]?.payload as ChartPoint | undefined;
                  return point?.date ? fechaCorta(point.date) : (point?.label ?? "");
                }}
                formatter={(value, name) => [`${numero(Number(value), 2)} %`, String(name)]}
              />
              <Bar
                yAxisId="quality"
                dataKey="quality"
                name={t("cuenca.datos_validos")}
                fill={theme.grid}
                isAnimationActive={false}
              />
              <Line
                yAxisId="snow"
                type="monotone"
                dataKey="average"
                name={t("cuenca.media_historica")}
                stroke={theme.reference}
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
                name={t("cuenca.esta_temporada")}
                stroke={theme.series}
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
                connectNulls
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </ChartCard>
    </>
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
    });
  }

  return [...byDay.values()].sort((a, b) => a.hydro_day - b.hydro_day);
}
