import { t } from "../lib/copy";
import { fechaCorta } from "../lib/format";
import type { CatalogEntry } from "../lib/catalog";
import { snowRanges } from "../lib/snowRange";
import SnowRange from "./SnowRange";

const LABELS = {
  area: "cuenca.nieve_area",
  meanDepth: "cuenca.espesor_medio",
  peakDepth: "cuenca.espesor_maximo",
  value: "cuenca.rango_valor",
};

/** What the model says about the snow of one basin on the selected day: median and p10 to p90, from the qa scores
 *  of the snow_depth entry. It is a model estimate and says so. */
export default function BasinSnowRange({ entry, basinId }: { entry: CatalogEntry | null; basinId: string }) {
  const ranges = snowRanges(entry, `basin_${basinId}`);
  return (
    <section className="mt-3 rounded-md border border-line bg-panel p-3" aria-label={t("cuenca.rango_titulo")}>
      <h4 className="m-0 font-medium">
        {t("cuenca.rango_titulo")}
        {entry && <span className="tnum font-normal text-text-muted"> · {fechaCorta(entry.date)}</span>}
      </h4>
      <div className="mt-2">
        {ranges ? <SnowRange ranges={ranges} labels={LABELS} /> : <p className="m-0 text-small text-text-muted">{t("cuenca.sin_rango")}</p>}
      </div>
      <p className="m-0 mt-2 text-caption text-text-muted">{t("cuenca.rango_aviso")}</p>
    </section>
  );
}
