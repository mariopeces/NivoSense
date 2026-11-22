import type { ReactNode } from "react";
import { t } from "../lib/copy";
import { token } from "../lib/tokens";

// Recharts writes colours into SVG attributes, which need resolved values, so the tokens are read here.
export function chartTheme() {
  return {
    series: token("color-ink"),
    reference: token("color-text-muted"),
    secondary: token("color-status-gapfilled"),
    grid: token("color-line"),
    axis: token("color-line-strong"),
    tick: { fill: token("color-text-muted"), fontSize: 12 },
    tooltip: {
      background: token("color-panel"),
      border: `1px solid ${token("color-line")}`,
      borderRadius: token("radius-md"),
      boxShadow: token("shadow-popover"),
      fontSize: 12,
      color: token("color-text"),
    },
  };
}

type Props = {
  title: string;
  loading: boolean;
  error: string | null;
  /** Why the series is not there yet; shown instead of the chart. */
  pending: string | null;
  footer?: ReactNode;
  children: ReactNode;
};

export function ChartCard({ title, loading, error, pending, footer, children }: Props) {
  const message = loading ? t("cargando.grafico") : (error ?? null);
  return (
    <section className="mb-3 rounded-md border border-line p-3">
      <h4 className="mb-2 mt-0 text-small font-semibold">{title}</h4>
      {message ? (
        <p role={error ? "alert" : "status"} className={`m-0 text-small ${error ? "text-danger" : "text-text-muted"}`}>
          {message}
        </p>
      ) : pending ? (
        <>
          <div className="grid h-[96px] place-items-center rounded-sm border border-dotted border-status-pending text-small text-text-muted">
            {t("cuenca.pendiente")}
          </div>
          <p className="mb-0 mt-2 text-small text-text-muted">{pending}</p>
        </>
      ) : (
        <>
          {children}
          {footer && <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-caption text-text-muted">{footer}</div>}
        </>
      )}
    </section>
  );
}
