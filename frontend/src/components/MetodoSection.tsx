import { t } from "../lib/copy";
import { GroupLabel } from "./ui";

export const LAYERS = ["nieve_observada", "nieve_diaria", "swe", "espesor", "color_real"];

// What each snow section says, in the order a reader asks it: what it is, how it is made, what it was checked
// against and what is not known. Every sentence comes from the copy deck, written from docs/snow-evaluation.md.
const SECTIONS: Array<{ title: string; blocks: Array<[heading: string, text: string]> }> = [
  {
    title: "metodo.seccion_nieve_observada",
    blocks: [
      ["metodo.fuente_y_licencia", "metodo.fuente_nieve_observada"],
      ["metodo.como_se_calcula", "metodo.nieve_observada_calculo_1"],
      ["metodo.como_se_calcula", "metodo.nieve_observada_calculo_2"],
      ["metodo.como_se_valida", "metodo.nieve_observada_validacion"],
    ],
  },
  {
    title: "metodo.seccion_nieve_diaria",
    blocks: [
      ["metodo.que_es", "metodo.nieve_diaria_que_es"],
      ["metodo.como_se_calcula", "metodo.nieve_diaria_calculo"],
      ["metodo.como_se_valida", "metodo.nieve_diaria_validacion"],
      ["metodo.lo_que_no_sabemos", "metodo.nieve_diaria_desconocido"],
    ],
  },
  {
    title: "metodo.seccion_modelo",
    blocks: [
      ["metodo.que_es", "metodo.modelo_que_es"],
      ["metodo.como_se_valida", "metodo.modelo_validacion"],
      ["metodo.lo_que_no_sabemos", "metodo.modelo_desconocido"],
      ["metodo.datos_que_ayudarian", "metodo.modelo_datos"],
      ["metodo.seccion_swe", "metodo.swe_bloqueada"],
    ],
  },
];

// The facts each layer's method section opens with (source, resolution, frequency), from the copy deck,
// then the sections that explain the snow layers. The full method page is its own screen in the spec.
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
      {SECTIONS.map((section) => (
        <section key={section.title} aria-label={t(section.title)}>
          <GroupLabel>{t(section.title)}</GroupLabel>
          {section.blocks.map(([heading, text]) => (
            <article key={text} className="mb-2 rounded-md border border-line p-3">
              <h4 className="m-0 text-small font-medium">{t(heading)}</h4>
              <p className="m-0 mt-1 text-small">{t(text)}</p>
            </article>
          ))}
        </section>
      ))}
    </>
  );
}
