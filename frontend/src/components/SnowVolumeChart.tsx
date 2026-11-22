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
import { t } from "../lib/copy";
import { fechaCorta, mesCorto, numero } from "../lib/format";
import type { BasinVolumeSeries, SnowModelBasin, SnowModelManifest } from "../lib/snowModel";
import { ChartCard, chartTheme } from "./chartTheme";

type Props = {
  basin: SnowModelBasin | null;
  manifest: SnowModelManifest | null;
  series: BasinVolumeSeries | null;
  loading: boolean;
  error: string | null;
};

export default function SnowVolumeChart({ basin, manifest, series, loading, error }: Props) {
  const theme = chartTheme();
  const model = manifest?.model;
  const calibration = model?.calibration;
  const previous = series?.previous_season;
  const length = Math.max(series?.dates.length ?? 0, previous?.dates.length ?? 0);
  const data = Array.from({ length }, (_, index) => ({
    day: index,
    date: series?.dates[index] ?? previous?.dates[index] ?? "",
    band:
      series && index < series.dates.length
        ? [series.swe_hm3.p10[index], series.swe_hm3.p90[index]]
        : undefined,
    median: series && index < series.dates.length ? series.swe_hm3.p50[index] : undefined,
    previous: previous && index < previous.dates.length ? previous.swe_hm3.p50[index] : undefined,
  }));
  const monthStarts = data.filter((point) => point.date.endsWith("-01")).map((point) => point.day);
  const latest = basin?.latest;
  // Until the model publishes, the series is pending, not failed: the spec's honest empty state.
  const pending = !loading && !error && (!model || model.status !== "available" || data.length === 0);

  return (
    <ChartCard
      title={`${t("cuenca.volumen")} (hm³)`}
      loading={loading}
      error={error ? t("error.serie") : null}
      pending={pending ? t("cuenca.pendiente_detalle") : null}
      footer={
        <>
          <span className="inline-flex items-center gap-1">
            <i className="inline-block w-4 border-t-2 border-ink" />
            {t("cuenca.esta_temporada")}
          </span>
          {previous && (
            <span className="inline-flex items-center gap-1">
              <i className="inline-block w-4 border-t-2 border-dashed border-text-muted" />
              {t("cuenca.temporada_anterior")}
            </span>
          )}
        </>
      }
    >
      {latest && (
        <dl className="mb-2 mt-0 grid grid-cols-2 gap-2">
          <div className="rounded-md bg-panel-soft p-3">
            <dt className="text-caption text-text-muted">{t("cuenca.volumen")}</dt>
            <dd className="tnum m-0 text-value">{numero(latest.swe_hm3.p50)} hm³</dd>
            <dd className="tnum m-0 text-caption text-text-muted">
              {t("cuenca.rango_p10_p90", { p10: numero(latest.swe_hm3.p10), p90: numero(latest.swe_hm3.p90) })}
            </dd>
          </div>
          <div className="rounded-md bg-panel-soft p-3">
            <dt className="text-caption text-text-muted">{t("cuenca.nieve_area")}</dt>
            <dd className="tnum m-0 text-value">{numero(latest.snow_area_km2.p50)} km²</dd>
            <dd className="tnum m-0 text-caption text-text-muted">{fechaCorta(latest.date)}</dd>
          </div>
        </dl>
      )}
      <div className="h-[170px]">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid stroke={theme.grid} vertical={false} />
            <XAxis
              dataKey="day"
              type="number"
              domain={[0, Math.max(length - 1, 1)]}
              ticks={monthStarts}
              tick={theme.tick}
              tickLine={false}
              axisLine={{ stroke: theme.axis }}
              tickFormatter={(day) => (data[day]?.date ? mesCorto(data[day].date) : "")}
            />
            <YAxis tick={theme.tick} tickLine={false} axisLine={false} width={40} />
            <Tooltip
              contentStyle={theme.tooltip}
              labelFormatter={(day) => (data[Number(day)]?.date ? fechaCorta(data[Number(day)].date) : "")}
              formatter={(value, name) =>
                Array.isArray(value)
                  ? [`${numero(Number(value[0]))} – ${numero(Number(value[1]))} hm³`, "p10 – p90"]
                  : [`${numero(Number(value))} hm³`, String(name)]
              }
            />
            <Area
              dataKey="band"
              name="p10 – p90"
              stroke="none"
              fill={theme.series}
              fillOpacity={0.15}
              isAnimationActive={false}
            />
            {previous && (
              <Line
                dataKey="previous"
                name={t("cuenca.temporada_anterior")}
                stroke={theme.reference}
                strokeWidth={1.5}
                strokeDasharray="4 4"
                dot={false}
                isAnimationActive={false}
              />
            )}
            <Line
              dataKey="median"
              name={t("cuenca.esta_temporada")}
              stroke={theme.series}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      {calibration && (
        <p className="mb-0 mt-2 text-caption text-text-muted">
          {t("cuenca.calibracion", {
            miembros: model?.members ?? "?",
            forzamiento: `${manifest?.forcing?.model ?? ""} (${manifest?.forcing?.provider ?? ""})`,
            f1: numero(calibration.metrics.posterior.f1, 2),
          })}{" "}
          <span className="text-warning">{t("leyenda.experimental")}</span>
        </p>
      )}
    </ChartCard>
  );
}
