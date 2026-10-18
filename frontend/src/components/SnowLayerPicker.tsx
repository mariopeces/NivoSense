import {
  SNOW_LAYERS,
  type SnowLayerId,
  type SnowModelManifest,
} from "../lib/snowModel";

type Props = {
  manifest: SnowModelManifest | null;
  loading: boolean;
  selected: SnowLayerId | null;
  onChange: (layer: SnowLayerId | null) => void;
};

export default function SnowLayerPicker({ manifest, loading, selected, onChange }: Props) {
  const unavailableReason =
    manifest?.model.status === "unavailable"
      ? (manifest.model.reasons[0] ?? "Snow model not available")
      : null;

  return (
    <div className="pointer-events-auto absolute right-16 top-20 z-20 rounded-xl border border-white/10 bg-[#081020]/85 px-2 py-2 backdrop-blur-xl">
      <div className="flex items-center gap-1">
        <span className="px-2 text-[10px] uppercase tracking-[0.16em] text-slate-500">
          {loading ? "Snow..." : "Snow"}
        </span>
        {SNOW_LAYERS.map((layer) => {
          const available = Boolean(manifest?.layers[layer.id]);
          return (
            <button
              key={layer.id}
              onClick={() => onChange(selected === layer.id ? null : layer.id)}
              disabled={!available}
              aria-pressed={selected === layer.id}
              title={
                available
                  ? `${layer.title}, ${manifest?.layers[layer.id]?.date}`
                  : (unavailableReason ?? "No data available yet")
              }
              className={`rounded-full px-3 py-1.5 text-[13px] font-medium transition disabled:cursor-not-allowed disabled:opacity-25 ${
                selected === layer.id
                  ? "bg-cyan-300 text-slate-950"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {layer.label}
            </button>
          );
        })}
      </div>
      {unavailableReason && (
        <p className="mt-1.5 max-w-[300px] px-2 text-[11px] leading-snug text-amber-300/80">
          Snow model: {unavailableReason}
        </p>
      )}
    </div>
  );
}
