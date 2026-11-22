import { Eye, EyeOff } from "lucide-react";
import { Icon } from "../lib/icons";
import { t } from "../lib/copy";
import { fechaCorta } from "../lib/format";
import type { SnowLayerId, SnowModelManifest } from "../lib/snowModel";
import { GroupLabel, Skeleton, StatusBadge, type Status } from "./ui";

type Props = {
  manifest: SnowModelManifest | null;
  loading: boolean;
  selected: SnowLayerId | null;
  onChange: (layer: SnowLayerId | null) => void;
};

// Rows in the order of the spec's Nieve panel. `layer` is the snow-model manifest layer that publishes it
// today, if any, and `todaySource` what that layer is really made from (pipelines/snow_model/run.py reads
// Sentinel-2 L2A for both its snow mask and its true colour). Layers with no publisher yet keep their row
// as Pendiente so they have a home.
type Row = { copy: string; status: Status; layer: SnowLayerId | null; todaySource?: string };

const SNOW_ROWS: Row[] = [
  { copy: "nieve_observada", status: "observado", layer: "observed_snow_10m", todaySource: "Sentinel-2 L2A" },
  { copy: "nieve_diaria", status: "rellenado", layer: null },
  { copy: "swe", status: "modelado", layer: "swe" },
  { copy: "espesor", status: "modelado", layer: "depth" },
];
const IMAGE_ROWS: Row[] = [{ copy: "color_real", status: "observado", layer: "s2_true_colour", todaySource: "Sentinel-2 L2A" }];

export default function NieveSection({ manifest, loading, selected, onChange }: Props) {
  if (loading) return <Skeleton label={t("cargando.catalogo")} />;
  const row = (item: Row) => (
    <LayerRow key={item.copy} row={item} manifest={manifest} selected={selected} onChange={onChange} />
  );
  return (
    <>
      <GroupLabel>{t("panel.grupo_capas_nieve")}</GroupLabel>
      {SNOW_ROWS.map(row)}
      <GroupLabel>{t("panel.grupo_imagen")}</GroupLabel>
      {IMAGE_ROWS.map(row)}
    </>
  );
}

function LayerRow({
  row,
  manifest,
  selected,
  onChange,
}: {
  row: Row;
  manifest: SnowModelManifest | null;
  selected: SnowLayerId | null;
  onChange: (layer: SnowLayerId | null) => void;
}) {
  const info = row.layer ? manifest?.layers[row.layer] : undefined;
  const name = t(`capa.${row.copy}.nombre`);
  const on = Boolean(row.layer && info && selected === row.layer);
  // What is published today wins over what the spec plans: today's 10 m observed snow is not the 20 m
  // product, and today's true colour is not L1C.
  const meta = t("fila_capa.meta", {
    fuente: (info && row.todaySource) || t(`capa.${row.copy}.fuente`),
    resolucion: info?.resolution_m ? `${info.resolution_m} m` : t(`capa.${row.copy}.resolucion`),
  });

  return (
    <div
      className={`mb-2 rounded-md border ${on ? "border-line-strong bg-panel" : "border-line"} ${
        info ? "bg-panel" : "bg-panel-soft"
      }`}
    >
      <div className="flex items-start gap-3 p-3">
        <button
          type="button"
          disabled={!info}
          aria-pressed={on}
          aria-label={t(on ? "fila_capa.ocultar" : "fila_capa.mostrar", { capa: name })}
          title={info ? t(on ? "fila_capa.ocultar" : "fila_capa.mostrar", { capa: name }) : t("fila_capa.pendiente")}
          onClick={() => row.layer && onChange(on ? null : row.layer)}
          className={`grid h-8 w-8 flex-none place-items-center rounded-md ${
            on ? "text-text" : "text-text-muted"
          } hover:bg-panel-soft disabled:cursor-not-allowed disabled:hover:bg-transparent`}
        >
          <Icon icon={on ? Eye : EyeOff} />
        </button>
        <div className="min-w-0 flex-1">
          <p className="m-0 font-medium">{name}</p>
          <p className="m-0 text-small text-text-muted">{meta}</p>
          {info ? (
            <>
              <p className="tnum mb-2 mt-1 text-small">
                {t("fila_capa.fecha_observacion", { fecha_corta: fechaCorta(info.date) })}
              </p>
              <StatusBadge status={row.status} />
            </>
          ) : (
            <>
              <p className="mb-2 mt-1 text-small text-text-muted">{t("fila_capa.pendiente_detalle")}</p>
              <StatusBadge status="pendiente" />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
