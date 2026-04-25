import { useEffect } from "react";
import { CloseIcon } from "../lib/icons";
import type { Basin } from "../lib/types";

type Props = {
  open: boolean;
  basins: Basin[];
  onClose: () => void;
  onSelect: (basinId: string) => void;
};

export default function StatsModal({ open, basins, onClose, onSelect }: Props) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="pointer-events-auto absolute inset-0 z-40 flex items-center justify-center bg-slate-950/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-[420px] max-w-[90vw] rounded-2xl border border-white/10 bg-slate-950/95 shadow-[0_30px_80px_-20px_rgba(0,0,0,0.8)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 border-b border-white/5 px-5 py-4">
          <div>
            <h2 className="text-base font-semibold tracking-tight text-white">
              Hydrographic basins
            </h2>
            <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
              Select a basin to outline it on the map and see its coverage
              evolution against the long-term average.
            </p>
          </div>
          <button
            onClick={onClose}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-slate-400 transition hover:bg-white/5 hover:text-slate-100"
            aria-label="Close"
          >
            <CloseIcon className="h-4 w-4" />
          </button>
        </div>

        <div className="max-h-[420px] overflow-y-auto p-3">
          {basins.length === 0 ? <EmptyState /> : (
            <ul className="space-y-1">
              {basins.map((b) => (
                <li key={b.id}>
                  <button
                    onClick={() => {
                      onSelect(b.id);
                      onClose();
                    }}
                    className="flex w-full items-center justify-between rounded-lg border border-white/5 bg-slate-900/40 px-3 py-2.5 text-left transition hover:border-cyan-400/30 hover:bg-slate-900/70"
                  >
                    <span className="text-sm text-slate-100">{b.name}</span>
                    {b.areaKm2 !== undefined && (
                      <span className="text-[11px] tabular-nums text-slate-500">
                        {b.areaKm2.toFixed(0)} km²
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="px-3 py-8 text-center">
      <div className="mx-auto mb-3 h-9 w-9 rounded-full border border-white/10 bg-slate-900/60" />
      <p className="text-sm text-slate-300">No basins loaded yet</p>
      <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
        Basins will appear here once <code className="text-slate-300">data/basins.geojson</code>{" "}
        is populated and served from the backend.
      </p>
    </div>
  );
}
