import type { LayerMode } from "./LeftRail";

type Props = {
  layer: LayerMode;
};

export default function Legend({ layer }: Props) {
  const config =
    layer === "cover"
      ? {
          title: "Snow cover",
          gradient:
            "linear-gradient(to right, #0f172a, #155e75, #22d3ee, #ecfeff)",
          left: "0%",
          right: "100%",
        }
      : {
          title: "Snow change",
          gradient:
            "linear-gradient(to right, #f87171, #1e293b, #67e8f9)",
          left: "−",
          right: "+",
        };

  return (
    <div className="pointer-events-auto absolute bottom-4 right-4 z-20 w-[220px] rounded-xl border border-white/5 bg-slate-950/80 px-3 py-2.5 backdrop-blur-xl shadow-[0_20px_40px_-12px_rgba(0,0,0,0.7)]">
      <div className="flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-[0.22em] text-slate-400">
          {config.title}
        </span>
      </div>
      <div
        className="mt-2 h-2 w-full rounded-full"
        style={{ background: config.gradient }}
      />
      <div className="mt-1.5 flex justify-between text-[10px] tabular-nums text-slate-500">
        <span>{config.left}</span>
        <span>{config.right}</span>
      </div>
    </div>
  );
}
