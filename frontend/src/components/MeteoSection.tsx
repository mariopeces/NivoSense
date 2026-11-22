import { t } from "../lib/copy";
import { fechaCorta, horaMadrid } from "../lib/format";
import {
  WEATHER_HORIZONS,
  WEATHER_VARIABLES,
  weatherField,
  type WeatherHorizon,
  type WeatherManifest,
  type WeatherVariable,
} from "../lib/weather";
import { GroupLabel, Notice, Skeleton } from "./ui";

type Props = {
  manifest: WeatherManifest | null;
  loading: boolean;
  horizon: WeatherHorizon | null;
  onHorizon: (horizon: WeatherHorizon | null) => void;
  modelId: string | null;
  onModel: (modelId: string) => void;
  variable: WeatherVariable;
  onVariable: (variable: WeatherVariable) => void;
};

const CHIP =
  "rounded-md border px-3 py-1 text-small font-medium transition-colors duration-fast " +
  "disabled:cursor-not-allowed disabled:border-dotted disabled:text-text-muted";
const chip = (active: boolean) =>
  `${CHIP} ${active ? "border-ink bg-ink text-on-ink-strong" : "border-line bg-panel hover:bg-panel-soft"}`;

export default function MeteoSection({
  manifest,
  loading,
  horizon,
  onHorizon,
  modelId,
  onModel,
  variable,
  onVariable,
}: Props) {
  if (loading) return <Skeleton label={t("cargando.capa", { capa: t("panel.meteo.titulo").toLowerCase() })} />;
  const models = manifest?.models ?? [];
  if (!models.length) return <Notice title={t("meteo.sin_prevision")} />;

  const unavailable = manifest?.unavailable_models ?? [];
  const model = models.find((item) => item.id === modelId);

  return (
    <>
      <GroupLabel>{t("meteo.modelo")}</GroupLabel>
      <div className="flex flex-wrap gap-2">
        {models.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => onModel(item.id)}
            aria-pressed={item.id === model?.id}
            title={t("meteo.pasada", { fecha_corta: fechaCorta(item.run_at), hora: horaMadrid(item.run_at) })}
            className={chip(item.id === model?.id)}
          >
            {item.name}
          </button>
        ))}
        {unavailable.map((item) => (
          <button key={item.id} type="button" disabled title={item.reason} className={chip(false)}>
            {item.name}
          </button>
        ))}
      </div>

      <GroupLabel>{t("meteo.variable")}</GroupLabel>
      <div className="flex flex-wrap gap-2">
        {WEATHER_VARIABLES.map((item) => {
          const field = weatherField(model, WEATHER_HORIZONS[0], item);
          return (
            <button
              key={item}
              type="button"
              onClick={() => onVariable(item)}
              disabled={!field?.available}
              aria-pressed={variable === item}
              title={field?.available ? undefined : field?.reason}
              className={chip(variable === item)}
            >
              {t(`meteo.${item}`)}
            </button>
          );
        })}
      </div>

      <GroupLabel>{t("meteo.horizonte")}</GroupLabel>
      <div className="flex flex-wrap gap-2">
        {WEATHER_HORIZONS.map((item) => {
          const field = weatherField(model, item, variable);
          return (
            <button
              key={item}
              type="button"
              onClick={() => onHorizon(horizon === item ? null : item)}
              disabled={!field?.available}
              aria-pressed={horizon === item}
              title={field?.available ? model?.horizons[String(item)]?.valid_at : field?.reason}
              className={`${chip(horizon === item)} tnum`}
            >
              {t("meteo.horas", { horas: item })}
            </button>
          );
        })}
      </div>
      <p className="mb-0 mt-3 text-small text-text-muted">{t("meteo.ayuda_horizonte")}</p>
    </>
  );
}
