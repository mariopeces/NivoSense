export type BasemapId = "dark" | "light" | "satellite";

type Props = {
  value: BasemapId;
  onChange: (id: BasemapId) => void;
};

const OPTIONS: { id: BasemapId; label: string }[] = [
  { id: "dark", label: "Dark" },
  { id: "light", label: "Light" },
  { id: "satellite", label: "Satellite" },
];

export default function BasemapSwitcher({ value, onChange }: Props) {
  return (
    <div className="pointer-events-auto absolute right-4 top-[200px] z-20">
      <div className="flex flex-col gap-0.5 rounded-xl border border-white/10 bg-slate-950/80 p-1 backdrop-blur-xl shadow-[0_10px_30px_-12px_rgba(0,0,0,0.7)]">
        {OPTIONS.map((opt) => {
          const active = opt.id === value;
          return (
            <button
              key={opt.id}
              onClick={() => onChange(opt.id)}
              className={`rounded-lg px-3 py-2 text-xs font-medium tracking-wide transition ${
                active
                  ? "bg-cyan-400/15 text-cyan-200 shadow-[inset_0_0_0_1px_rgba(34,211,238,0.35)]"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
