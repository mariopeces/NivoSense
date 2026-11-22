import { t } from "../lib/copy";
import { GroupLabel } from "./ui";

export const LAYERS = ["nieve_observada", "nieve_diaria", "swe", "espesor", "color_real"];

// The facts each layer's method section opens with (source, resolution, frequency), from the copy deck.
// The full method page is its own screen in the spec.
export default function MetodoSection() {
  return (
    <>
      <GroupLabel>{t("metodo.indice")}</GroupLabel>
      {LAYERS.map((layer) => (
        <article key={layer} className="mb-2 rounded-md border border-line p-3">
          <h3 className="m-0 font-medium">{t(`capa.${layer}.nombre`)}</h3>
          <dl className="mb-2 mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-small">
            <dt className="text-text-muted">{t("info_capa.fuente")}</dt>
            <dd className="m-0">{t(`capa.${layer}.fuente`)}</dd>
            <dt className="text-text-muted">{t("info_capa.resolucion")}</dt>
            <dd className="m-0">{t(`capa.${layer}.resolucion`)}</dd>
            <dt className="text-text-muted">{t("info_capa.cadencia")}</dt>
            <dd className="m-0">{t(`capa.${layer}.cadencia`)}</dd>
          </dl>
          <p className="m-0 text-small text-text-muted">{t(`capa.${layer}.descripcion`)}</p>
        </article>
      ))}
    </>
  );
}
