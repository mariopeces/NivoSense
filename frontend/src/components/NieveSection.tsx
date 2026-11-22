import { useEffect, useRef, useState, type ReactNode } from "react";
import { Eye, EyeOff, Info, RotateCw, X } from "lucide-react";
import { Icon } from "../lib/icons";
import { t } from "../lib/copy";
import { fechaCorta } from "../lib/format";
import type { CatalogEntry, CatalogState } from "../lib/catalog";
import { RAMPS, entryFor, layerSpecs, type LayerSpec } from "../lib/layers";
import { STATUS_OF } from "../lib/timeline";
import type { VisibleLayers } from "../lib/urlState";
import RampLegend from "./RampLegend";
import { GroupLabel, Notice, Skeleton, StatusBadge } from "./ui";

type Props = {
  catalog: CatalogState;
  date: string | null;
  visible: VisibleLayers;
  onToggle: (id: string) => void;
  onOpacity: (id: string, opacity: number) => void;
  onDate: (date: string) => void;
  onMethod: () => void;
  onRetry: () => void;
};

const ICON_BUTTON =
  "grid h-8 w-8 flex-none place-items-center rounded-md text-text-muted hover:bg-panel-soft hover:text-text " +
  "disabled:cursor-not-allowed disabled:hover:bg-transparent max-md:h-touch max-md:w-touch";

// One row per catalogue layer. Rows come from the catalogue, never from sample data: a layer with no entry
// keeps its row and legend as Pendiente so the reader learns it before it exists.
export default function NieveSection({ catalog, date, visible, onToggle, onOpacity, onDate, onMethod, onRetry }: Props) {
  if (catalog.kind === "loading") return <Skeleton label={t("cargando.catalogo")} />;
  const index = catalog.kind === "ready" ? catalog.index : null;
  const empty = !index || Object.values(index.layers).every((layer) => layer.entries.length === 0);
  const specs = layerSpecs(index);
  const row = (spec: LayerSpec) => {
    const shown = visible.find((item) => item.id === spec.id);
    return (
      <LayerRow
        key={spec.id}
        spec={spec}
        entries={index?.layers[spec.id]?.entries ?? []}
        date={date}
        opacity={shown?.opacity ?? null}
        onToggle={() => onToggle(spec.id)}
        onOpacity={(value) => onOpacity(spec.id, value)}
        onDate={onDate}
        onMethod={onMethod}
      />
    );
  };
  return (
    <>
      {catalog.kind === "error" && (
        <Notice title={t("error.catalogo_titulo")} error>
          <p className="m-0">{t("error.catalogo_detalle")}</p>
          <button
            type="button"
            onClick={onRetry}
            className="mt-2 inline-flex h-8 items-center gap-2 rounded-md border border-line bg-panel px-3 text-small font-medium text-text hover:bg-panel-soft"
          >
            <Icon icon={RotateCw} />
            {t("error.reintentar")}
          </button>
        </Notice>
      )}
      {catalog.kind !== "error" && empty && (
        <Notice title={t("vacio.sin_catalogo_titulo")}>{t("vacio.sin_catalogo_detalle")}</Notice>
      )}
      <GroupLabel>{t("panel.grupo_capas_nieve")}</GroupLabel>
      {specs.filter((spec) => spec.group === "nieve").map(row)}
      <GroupLabel>{t("panel.grupo_imagen")}</GroupLabel>
      {specs.filter((spec) => spec.group === "imagen").map(row)}
    </>
  );
}

function LayerRow({
  spec,
  entries,
  date,
  opacity,
  onToggle,
  onOpacity,
  onDate,
  onMethod,
}: {
  spec: LayerSpec;
  entries: CatalogEntry[];
  date: string | null;
  opacity: number | null;
  onToggle: () => void;
  onOpacity: (value: number) => void;
  onDate: (date: string) => void;
  onMethod: () => void;
}) {
  const [infoOpen, setInfoOpen] = useState(false);
  const infoButton = useRef<HTMLButtonElement | null>(null);
  const shown = date ? entryFor(entries, date) : null;
  const entry = shown?.entry ?? null;
  const on = opacity !== null && entry !== null;
  const name = spec.copy ? t(`capa.${spec.copy}.nombre`) : spec.id;
  const resolution = entry ? `${entry.resolution_m} m` : spec.copy ? t(`capa.${spec.copy}.resolucion`) : "";
  const meta = spec.copy ? t("fila_capa.meta", { fuente: t(`capa.${spec.copy}.fuente`), resolucion: resolution }) : resolution;
  const toggleLabel = t(on ? "fila_capa.ocultar" : "fila_capa.mostrar", { capa: name });
  const sliderId = `opacidad-${spec.id}`;

  return (
    <div className={`mb-2 rounded-md border ${on ? "border-line-strong bg-panel" : "border-line"} ${entry ? "bg-panel" : "bg-panel-soft"}`}>
      <div className="flex items-start gap-2 p-3 pb-2">
        <button
          type="button"
          disabled={!entry}
          aria-pressed={on}
          aria-label={toggleLabel}
          title={entry ? toggleLabel : t("fila_capa.pendiente")}
          onClick={onToggle}
          className={`${ICON_BUTTON} ${on ? "text-text" : ""}`}
        >
          <Icon icon={on ? Eye : EyeOff} />
        </button>
        <div className="min-w-0 flex-1">
          <p className="m-0 font-medium">{name}</p>
          {meta && <p className="m-0 text-small text-text-muted">{meta}</p>}
          {entry && shown?.exact && (
            <p className="tnum m-0 mt-1 text-small">{t("fila_capa.fecha_observacion", { fecha_corta: fechaCorta(entry.date) })}</p>
          )}
          {entry && !shown?.exact && (
            <p className="tnum m-0 mt-1 text-small">
              {t("fila_capa.sin_escena_en_fecha", { fecha_corta: fechaCorta(entry.date) })}{" "}
              <button
                type="button"
                onClick={() => onDate(entry.date)}
                className="rounded-sm font-medium text-accent-text underline underline-offset-2 hover:no-underline"
              >
                {t("fila_capa.ir_a_escena", { fecha_corta: fechaCorta(entry.date) })}
              </button>
            </p>
          )}
          {!entry && <p className="m-0 mt-1 text-small text-text-muted">{t("fila_capa.pendiente_detalle")}</p>}
          <div className="mt-2">
            <StatusBadge status={entry ? STATUS_OF[entry.status] : "pendiente"} />
          </div>
        </div>
        <button
          ref={infoButton}
          type="button"
          aria-expanded={infoOpen}
          aria-haspopup="dialog"
          aria-label={t("fila_capa.info", { capa: name })}
          title={t("fila_capa.info", { capa: name })}
          onClick={() => setInfoOpen((value) => !value)}
          className={ICON_BUTTON}
        >
          <Icon icon={Info} />
        </button>
      </div>
      {infoOpen && (
        <LayerInfo
          spec={spec}
          name={name}
          entry={entry}
          resolution={resolution}
          onMethod={onMethod}
          onClose={() => {
            setInfoOpen(false);
            infoButton.current?.focus();
          }}
        />
      )}
      <div className="px-3 pb-3">
        {spec.ramp && <RampLegend rampId={spec.ramp} />}
        <div className="mt-2 flex items-center gap-3 text-small">
          <label htmlFor={sliderId} className={on ? "" : "text-text-muted"}>
            {t("fila_capa.opacidad")}
          </label>
          <input
            id={sliderId}
            type="range"
            min={0}
            max={100}
            step={5}
            value={opacity ?? 100}
            disabled={!on}
            onChange={(event) => onOpacity(Number(event.target.value))}
            aria-valuetext={t("fila_capa.opacidad_valor", { valor: opacity ?? 100 })}
            className="min-w-0 flex-1 accent-accent disabled:cursor-not-allowed"
          />
          <span className={`tnum w-12 text-right ${on ? "" : "text-text-muted"}`}>
            {t("fila_capa.opacidad_valor", { valor: opacity ?? 100 })}
          </span>
        </div>
      </div>
    </div>
  );
}

function LayerInfo({
  spec,
  name,
  entry,
  resolution,
  onMethod,
  onClose,
}: {
  spec: LayerSpec;
  name: string;
  entry: CatalogEntry | null;
  resolution: string;
  onMethod: () => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  // Mount only, so a re-render while it is open does not move focus.
  useEffect(() => {
    ref.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCloseRef.current();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const unit = spec.ramp ? RAMPS[spec.ramp].unit : null;
  const rows: Array<[string, ReactNode]> = [
    ["info_capa.fuente", spec.copy ? t(`capa.${spec.copy}.fuente`) : spec.id],
    ["info_capa.resolucion", resolution],
    ...(spec.copy ? ([["info_capa.cadencia", t(`capa.${spec.copy}.cadencia`)]] as Array<[string, string]>) : []),
    ["info_capa.fecha_dato", entry ? fechaCorta(entry.date) : t("fila_capa.pendiente")],
    ["info_capa.estado", <StatusBadge key="estado" status={entry ? STATUS_OF[entry.status] : "pendiente"} />],
    ...(unit ? ([["info_capa.unidades", unit]] as Array<[string, string]>) : []),
  ];

  return (
    <div
      ref={ref}
      role="dialog"
      tabIndex={-1}
      aria-label={`${t("info_capa.titulo")}: ${name}`}
      className="mx-3 mb-3 rounded-lg bg-panel p-3 shadow-popover outline-none"
    >
      <div className="flex items-center justify-between gap-2">
        <p className="m-0 font-semibold">{t("info_capa.titulo")}</p>
        <button type="button" onClick={onClose} aria-label={t("info_capa.cerrar")} title={t("info_capa.cerrar")} className={ICON_BUTTON}>
          <Icon icon={X} />
        </button>
      </div>
      {spec.copy && <p className="m-0 mt-1 text-small">{t(`capa.${spec.copy}.descripcion`)}</p>}
      <dl className="m-0 mt-2 grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 gap-y-1 text-small">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-text-muted">{t(label)}</dt>
            <dd className="tnum m-0">{value}</dd>
          </div>
        ))}
        {entry && (
          <div className="contents">
            <dt className="self-start text-text-muted">{t("info_capa.escenas")}</dt>
            <dd className="m-0">
              <ul className="m-0 list-none break-all p-0 text-caption">
                {entry.source_ids.map((id) => (
                  <li key={id}>{id}</li>
                ))}
              </ul>
            </dd>
          </div>
        )}
      </dl>
      <button type="button" onClick={onMethod} className="mt-2 rounded-sm text-small font-medium text-accent-text underline underline-offset-2 hover:no-underline">
        {t("info_capa.metodo")}
      </button>
    </div>
  );
}
