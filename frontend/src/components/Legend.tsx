import type { SnowOverlay } from "../lib/snowModel";
import type { WeatherOverlay, WeatherVariable } from "../lib/weather";
import { t } from "../lib/copy";
import { fechaCorta, horaMadrid, numero } from "../lib/format";
import { StatusBadge } from "./ui";

type Props = {
  weatherOverlay: WeatherOverlay | null;
  snowOverlay: SnowOverlay | null;
};

// These are data colours, not UI tokens: each one copies the palette that today's pipelines bake into the
// PNG on the map (PALETTES and SNOW_RGB in pipelines/snow_model/outputs.py, PALETTES in
// pipelines/weather_forecasts/raster.py, both interpolated at stops 0, 0.2, 0.45, 0.7 and 1), so the legend
// says exactly what the image shows. They go when the pipelines colour with docs/design/ramps.json and the
// legends read that file.
const STOPS = [0, 20, 45, 70, 100];
const PIPELINE_PALETTES = {
  swe: ["#142163", "#2f61d6", "#60a5fa", "#bae6fd", "#ffffff"],
  depth: ["#3c2878", "#6366f1", "#81b4fa", "#cfe9fe", "#ffffff"],
  precipitation_total: ["#082f49", "#0e7490", "#06b6d4", "#22d3ee", "#ecfeff"],
  snowfall: ["#2d236e", "#4f46e5", "#818cf8", "#c7d2fe", "#ffffff"],
};
const OBSERVED_SNOW = "#67e8f9";
const OBSERVED_GAP = "rgba(120, 130, 145, 0.43)";
const MIN_VISIBLE_MM = 0.1;

function gradient(colours: string[]) {
  return `linear-gradient(to right, ${colours.map((c, i) => `${c} ${STOPS[i]}%`).join(", ")})`;
}

const CARD = "shell-legend absolute z-map-controls w-[280px] rounded-md bg-panel px-3 py-2 shadow-float max-md:hidden";

function Ramp({ colours, from, to }: { colours: string[]; from: string; to: string }) {
  return (
    <>
      <div className="mt-2 h-3 rounded-sm border border-line" style={{ background: gradient(colours) }} />
      <div className="tnum mt-1 flex justify-between text-caption text-text-muted">
        <span>{from}</span>
        <span>{to}</span>
      </div>
    </>
  );
}

function SnowLegend({ overlay }: { overlay: SnowOverlay }) {
  const { info } = overlay;
  const date = fechaCorta(info.date);
  if (overlay.layer === "s2_true_colour") {
    return (
      <div className={CARD}>
        <p className="m-0 font-medium">{t("leyenda.chip_mapa", { capa: t("capa.color_real.nombre"), fecha_corta: date })}</p>
        <p className="tnum mb-0 mt-1 text-caption text-text-muted">
          {t("leyenda.despejado", { valor: Math.round((info.valid_fraction ?? 0) * 100) })}
        </p>
      </div>
    );
  }
  if (overlay.layer === "observed_snow_10m") {
    return (
      <div className={CARD}>
        <p className="m-0 font-medium">{t("leyenda.chip_mapa", { capa: t("capa.nieve_observada.nombre"), fecha_corta: date })}</p>
        <div className="mt-2 grid gap-1 text-caption">
          <span className="flex items-center gap-2">
            <span className="h-4 w-4 rounded-sm border border-line-strong" style={{ background: OBSERVED_SNOW }} />
            {t("leyenda.nieve")}
          </span>
          <span className="flex items-center gap-2">
            <span className="h-4 w-4 rounded-sm border border-line-strong" style={{ background: OBSERVED_GAP }} />
            {t("leyenda.nube_o_sin_dato")}
          </span>
        </div>
        <p className="tnum mb-0 mt-2 text-caption text-text-muted">
          {t("leyenda.despejado_nieve", {
            valor: Math.round((info.valid_fraction ?? 0) * 100),
            nieve: numero((info.snow_fraction_of_valid ?? 0) * 100),
          })}
        </p>
      </div>
    );
  }
  const swe = overlay.layer === "swe";
  const unit = swe ? "mm" : "m";
  return (
    <div className={CARD}>
      <div className="flex items-center justify-between gap-2">
        <p className="m-0 font-medium">{t(swe ? "leyenda.swe" : "leyenda.espesor_m")}</p>
        <StatusBadge status="modelado" />
      </div>
      <Ramp
        colours={PIPELINE_PALETTES[overlay.layer]}
        from={`${info.minimum_visible} ${unit}`}
        to={`${info.scale_max} ${unit}`}
      />
      <p className="tnum mb-0 mt-1 text-caption text-text-muted">{t("leyenda.media_conjunto", { fecha_corta: date })}</p>
      <p className="mb-0 mt-1 text-caption text-warning">{t("leyenda.experimental")}</p>
    </div>
  );
}

const WEATHER_TITLE: Record<WeatherVariable, string> = {
  precipitation_total: "leyenda.precipitacion_acumulada",
  snowfall: "leyenda.nieve_acumulada",
};

function WeatherLegend({ overlay }: { overlay: WeatherOverlay }) {
  return (
    <div className={CARD}>
      <div className="flex items-center justify-between gap-2">
        <p className="m-0 font-medium">{t(WEATHER_TITLE[overlay.variable])}</p>
        <StatusBadge status="prevision" />
      </div>
      <Ramp
        colours={PIPELINE_PALETTES[overlay.variable]}
        from={`${numero(MIN_VISIBLE_MM)} mm`}
        to={`${numero(overlay.scaleMaxMm)} mm`}
      />
      <p className="mb-0 mt-1 text-caption text-text-muted">
        {overlay.regionMaxMm < MIN_VISIBLE_MM
          ? t("leyenda.sin_valores", { valor: numero(MIN_VISIBLE_MM) })
          : t("leyenda.maximo_regional", { valor: numero(overlay.regionMaxMm) })}
      </p>
      <dl className="tnum mb-0 mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 border-t border-line pt-2 text-caption">
        <dt className="text-text-muted">{t("leyenda.modelo")}</dt>
        <dd className="m-0 text-right">{overlay.modelName}</dd>
        <dt className="text-text-muted">{t("info_capa.resolucion")}</dt>
        <dd className="m-0 text-right">
          {numero(overlay.gridDegrees, 2)}° (~{Math.round(overlay.gridDegrees * 111)} km)
        </dd>
        <dt className="text-text-muted">{t("leyenda.pasada")}</dt>
        <dd className="m-0 text-right">
          {fechaCorta(overlay.runAt)}, {horaMadrid(overlay.runAt)}
        </dd>
        <dt className="text-text-muted">{t("leyenda.valida")}</dt>
        <dd className="m-0 text-right">
          {fechaCorta(overlay.validAt)}, {horaMadrid(overlay.validAt)}
        </dd>
      </dl>
      {overlay.note && <p className="mb-0 mt-2 text-caption text-warning">{overlay.note}</p>}
      <p className="mb-0 mt-2 text-caption text-text-muted">{overlay.attribution}</p>
    </div>
  );
}

export default function Legend({ weatherOverlay, snowOverlay }: Props) {
  if (weatherOverlay) return <WeatherLegend overlay={weatherOverlay} />;
  if (snowOverlay) return <SnowLegend overlay={snowOverlay} />;
  return null;
}
