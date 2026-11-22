import { t } from "../lib/copy";
import { numero } from "../lib/format";
import { RAMPS, rampBounds, type RampClass } from "../lib/layers";

// Units line and transparent-class note of each stepped ramp, from the copy deck.
const UNIT_LABEL: Record<string, string> = {
  snow_cover_probability: "leyenda.probabilidad",
  swe: "leyenda.swe",
  snow_depth: "leyenda.espesor",
};
const TRANSPARENT_NOTE: Record<string, string> = {
  snow_cover_probability: "leyenda.transparente_probabilidad",
  swe: "leyenda.transparente_swe",
};

const SWATCH = 16;

/** A class swatch as the pipelines paint it: fill at its alpha, then its dots or 45 degree hatch on top. */
export function ClassSwatch({ cls }: { cls: RampClass }) {
  const pattern = cls.pattern;
  const marks: JSX.Element[] = [];
  if (pattern?.kind === "dots") {
    for (let y = pattern.spacing_px / 2; y < SWATCH; y += pattern.spacing_px) {
      for (let x = pattern.spacing_px / 2; x < SWATCH; x += pattern.spacing_px) {
        marks.push(<circle key={`${x}-${y}`} cx={x} cy={y} r={pattern.radius_px ?? 1} />);
      }
    }
  } else if (pattern?.kind === "hatch") {
    for (let k = -SWATCH; k < SWATCH; k += pattern.spacing_px) {
      marks.push(<line key={k} x1={k} y1={SWATCH} x2={k + SWATCH} y2={0} strokeWidth={pattern.width_px ?? 1} />);
    }
  }
  return (
    <svg width={SWATCH} height={SWATCH} viewBox={`0 0 ${SWATCH} ${SWATCH}`} aria-hidden="true" className="flex-none overflow-hidden rounded-sm">
      {cls.color && <rect width={SWATCH} height={SWATCH} fill={cls.color} fillOpacity={cls.alpha} />}
      {pattern && (
        <g fill={pattern.color} stroke={pattern.color} opacity={pattern.alpha ?? 1}>
          {marks}
        </g>
      )}
      <rect x={0.5} y={0.5} width={SWATCH - 1} height={SWATCH - 1} fill="none" className="stroke-line-strong" />
    </svg>
  );
}

export default function RampLegend({ rampId }: { rampId: string }) {
  const ramp = RAMPS[rampId];
  if (ramp.categorical) {
    return (
      <ul className="m-0 grid list-none gap-1 p-0 text-caption">
        {ramp.classes.map((cls) => (
          <li key={cls.key} className="flex items-center gap-2">
            <ClassSwatch cls={cls} />
            {cls.label_es}
          </li>
        ))}
      </ul>
    );
  }
  const percent = ramp.unit === "%";
  const bounds = rampBounds(ramp);
  return (
    <div>
      <div className="flex h-3 overflow-hidden rounded-sm border border-line" aria-hidden="true">
        {ramp.classes.map((cls, i) =>
          cls.color ? (
            <span key={i} className="flex-1" style={{ backgroundColor: cls.color, opacity: cls.alpha }} />
          ) : (
            <span key={i} className="flex-1 border-r border-dashed border-line-strong bg-panel" />
          ),
        )}
      </div>
      <div className="tnum relative mt-1 h-4 text-caption text-text-muted" aria-hidden="true">
        {bounds.map((bound, i) => (
          <span
            key={i}
            className={`absolute ${i === 0 ? "" : i === ramp.classes.length ? "-translate-x-full" : "-translate-x-1/2"}`}
            style={{ left: `${(100 * i) / ramp.classes.length}%` }}
          >
            {numero(percent ? bound * 100 : bound, 0)}
          </span>
        ))}
      </div>
      {/* The steps are drawn for sighted readers; the class list carries the same values for everyone. */}
      <ul className="sr-only">
        {ramp.classes.map((cls, i) => (
          <li key={i}>{cls.label_es}</li>
        ))}
      </ul>
      <p className="m-0 mt-1 text-caption text-text-muted">
        {t(UNIT_LABEL[rampId])}
        {TRANSPARENT_NOTE[rampId] ? ` · ${t(TRANSPARENT_NOTE[rampId])}` : ""}
      </p>
    </div>
  );
}
