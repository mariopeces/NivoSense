import type { ReactNode } from "react";
import { t } from "../lib/copy";

export type Status = "observado" | "rellenado" | "modelado" | "prevision" | "pendiente";

// Status is carried by shape as well as colour (solid, outline, half, dashed, dotted), so it survives
// colour blindness and greyscale.
const BADGE: Record<Status, { text: string; border: string; glyph: string }> = {
  observado: { text: "text-status-observed", border: "border-solid", glyph: "bg-current" },
  rellenado: { text: "text-status-gapfilled", border: "border-solid", glyph: "border-[1.5px] border-current" },
  modelado: {
    text: "text-status-modelled",
    border: "border-solid",
    glyph: "border-[1.5px] border-current bg-gradient-to-t from-current from-50% to-transparent to-50%",
  },
  prevision: { text: "text-status-forecast", border: "border-dashed", glyph: "border-[1.5px] border-dashed border-current" },
  pendiente: { text: "text-status-pending", border: "border-dotted", glyph: "border-[1.5px] border-dotted border-current" },
};

export function StatusBadge({ status }: { status: Status }) {
  const style = BADGE[status];
  return (
    <span
      title={t(`estado.tooltip_${status}`)}
      className={`inline-flex h-5 items-center gap-1 whitespace-nowrap rounded-sm border px-2 text-caption ${style.text} ${style.border}`}
    >
      <span aria-hidden="true" className={`h-2 w-2 rounded-sm ${style.glyph}`} />
      {t(`estado.${status}`)}
    </span>
  );
}

export function GroupLabel({ children }: { children: ReactNode }) {
  return <h3 className="mx-1 mb-2 mt-4 text-eyebrow text-text-muted first:mt-0">{children}</h3>;
}

export function Notice({ title, children, error = false }: { title: string; children?: ReactNode; error?: boolean }) {
  return (
    <div
      role={error ? "alert" : "status"}
      className={`mb-3 rounded-md bg-panel-soft px-4 py-3 ${error ? "border-l-[3px] border-danger" : ""}`}
    >
      <p className="m-0 font-medium">{title}</p>
      {children && <div className="mt-1 text-small text-text-muted">{children}</div>}
    </div>
  );
}

export function Skeleton({ label }: { label: string }) {
  return (
    <div role="status" aria-live="polite" aria-busy="true">
      <span className="sr-only">{label}</span>
      {[0, 1, 2].map((key) => (
        <div key={key} className="mb-2 h-[72px] rounded-md bg-panel-soft" />
      ))}
    </div>
  );
}
