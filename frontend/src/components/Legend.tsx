import type { WeatherOverlay, WeatherVariable } from "../lib/weather";
import palettes from "../../../pipelines/weather_forecasts/palettes.json";
import { t } from "../lib/copy";
import { fechaCorta, horaMadrid, numero } from "../lib/format";
import type { CatalogLayer } from "./Map";
import { StatusBadge } from "./ui";

type Props = {
  weatherOverlay: WeatherOverlay | null;
  /** Bottom to top, as drawn. */
  layers: CatalogLayer[];
};

// The weather images are painted by pipelines/weather_forecasts/raster.py from the same palettes file, so the
// legend shows exactly the colours on the map.
const WEATHER_PALETTES = palettes.palettes as Record<WeatherVariable, string[]>;

function gradient(colours: string[]) {
  return `linear-gradient(to right, ${colours.map((c, i) => `${c} ${palettes.stops[i] * 100}%`).join(", ")})`;
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

// One line per visible catalogue layer, top layer first: what is on the map and the date of its data, which
// can differ from the map date when the layer has no product that day. The classes live in the panel rows.
function LayerChips({ layers }: { layers: CatalogLayer[] }) {
  return (
    <ul className={`${CARD} m-0 grid list-none gap-1`}>
      {[...layers].reverse().map((layer) => (
        <li key={layer.id} className="flex items-center justify-between gap-2">
          <span className="tnum min-w-0 font-medium">
            {t("leyenda.chip_mapa", { capa: layer.name, fecha_corta: fechaCorta(layer.date) })}
          </span>
          <StatusBadge status={layer.status} />
        </li>
      ))}
    </ul>
  );
}

const WEATHER_TITLE: Record<WeatherVariable, string> = {
  precipitation_total: "leyenda.precipitacion_acumulada",
  temperature_2m: "leyenda.temperatura",
  wind_speed_10m: "leyenda.viento",
};

function WeatherLegend({ overlay }: { overlay: WeatherOverlay }) {
  const precipitation = overlay.variable === "precipitation_total";
  return (
    <div className={CARD}>
      <div className="flex items-center justify-between gap-2">
        <p className="m-0 font-medium">{t(WEATHER_TITLE[overlay.variable])}</p>
        <StatusBadge status="prevision" />
      </div>
      {overlay.dry ? (
        <>
          <p className="mb-0 mt-2 font-medium">{t("leyenda.sin_precipitacion")}</p>
          <p className="mb-0 mt-1 text-caption text-text-muted">
            {t("leyenda.sin_precipitacion_detalle", { valor: numero(palettes.min_visible_mm) })}
          </p>
        </>
      ) : (
        <>
          <Ramp
            colours={WEATHER_PALETTES[overlay.variable]}
            from={`${numero(precipitation ? palettes.min_visible_mm : overlay.scaleMin, precipitation ? 1 : 0)} ${overlay.units}`}
            to={`${numero(overlay.scaleMax, precipitation ? 1 : 0)} ${overlay.units}`}
          />
          <p className="mb-0 mt-1 text-caption text-text-muted">
            {precipitation
              ? t("leyenda.maximo_regional", { valor: numero(overlay.regionMax) })
              : t("leyenda.rango_regional", {
                  minimo: numero(overlay.regionMin, 0),
                  maximo: numero(overlay.regionMax, 0),
                  unidades: overlay.units,
                })}
          </p>
        </>
      )}
      <dl className="tnum mb-0 mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 border-t border-line pt-2 text-caption">
        <dt className="text-text-muted">{t("leyenda.modelo")}</dt>
        <dd className="m-0 text-right">{overlay.modelName}</dd>
        <dt className="text-text-muted">{t("info_capa.resolucion")}</dt>
        <dd className="m-0 text-right">{overlay.resolution}</dd>
        <dt className="text-text-muted">{t("leyenda.pasada")}</dt>
        <dd className="m-0 text-right">
          {fechaCorta(overlay.runAt)}, {horaMadrid(overlay.runAt)}
        </dd>
        <dt className="text-text-muted">{t("leyenda.valida")}</dt>
        <dd className="m-0 text-right">
          {fechaCorta(overlay.validAt)}, {horaMadrid(overlay.validAt)}
        </dd>
      </dl>
      {overlay.experimental && <p className="mb-0 mt-2 text-caption text-warning">{t("leyenda.aviso_experimental")}</p>}
      {overlay.note && <p className="mb-0 mt-2 text-caption text-text-muted">{overlay.note}</p>}
      <p className="mb-0 mt-2 text-caption text-text-muted">{overlay.attribution}</p>
    </div>
  );
}

export default function Legend({ weatherOverlay, layers }: Props) {
  if (weatherOverlay) return <WeatherLegend overlay={weatherOverlay} />;
  if (layers.length) return <LayerChips layers={layers} />;
  return null;
}
