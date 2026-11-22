import type { ReactNode } from "react";
import { ArrowLeft } from "lucide-react";
import { Icon } from "../lib/icons";
import { t } from "../lib/copy";
import { numero } from "../lib/format";
import type { Basin } from "../lib/types";

type Props = {
  basins: Basin[];
  loading: boolean;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  /** Charts of the selected basin (snow and river flow). */
  children?: ReactNode;
};

export default function AguaSection({ basins, loading, selectedId, onSelect, children }: Props) {
  const selected = basins.find((basin) => basin.id === selectedId) ?? null;

  if (selected) {
    return (
      <>
        <button
          type="button"
          onClick={() => onSelect(null)}
          className="mb-3 inline-flex items-center gap-1 rounded-sm text-small text-text-muted hover:text-text"
        >
          <Icon icon={ArrowLeft} />
          {t("cuenca.volver")}
        </button>
        <h3 className="m-0 font-display text-title">{selected.name}</h3>
        {selected.areaKm2 != null && (
          <dl className="my-3 grid grid-cols-2 gap-2">
            <div className="rounded-md bg-panel-soft p-3">
              <dt className="text-caption text-text-muted">{t("cuenca.area")}</dt>
              <dd className="tnum m-0 mt-1 font-semibold">
                {t("cuenca.area_valor", { valor: numero(selected.areaKm2) })}
              </dd>
            </div>
          </dl>
        )}
        {children}
      </>
    );
  }

  if (loading) {
    return (
      <p role="status" className="m-0 text-small text-text-muted">
        {t("cargando.capa", { capa: t("capa.cuencas.nombre").toLowerCase() })}
      </p>
    );
  }

  return (
    <>
      <p className="mb-3 mt-0 text-small text-text-muted">{t("cuenca.seleccionar")}</p>
      <ul className="m-0 list-none p-0">
        {[...basins]
          .sort((a, b) => (b.areaKm2 ?? 0) - (a.areaKm2 ?? 0))
          .map((basin) => (
            <li key={basin.id}>
              <button
                type="button"
                onClick={() => onSelect(basin.id)}
                className="mb-2 flex w-full items-center justify-between gap-3 rounded-md border border-line bg-panel p-3 text-left hover:bg-panel-soft"
              >
                <span className="font-medium">{basin.name}</span>
                {basin.areaKm2 != null && (
                  <span className="tnum whitespace-nowrap text-small text-text-muted">
                    {numero(basin.areaKm2)} km²
                  </span>
                )}
              </button>
            </li>
          ))}
      </ul>
    </>
  );
}
