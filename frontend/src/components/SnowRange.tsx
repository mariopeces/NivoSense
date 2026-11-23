import { t } from "../lib/copy";
import { numero } from "../lib/format";
import type { Range, SnowRanges } from "../lib/snowRange";

type Labels = { area: string; meanDepth: string; peakDepth: string; value: string };

function value(labels: Labels, range: Range, unit: string, decimals: number) {
  return t(labels.value, {
    p10: numero(range.p10, decimals),
    p50: numero(range.p50, decimals),
    p90: numero(range.p90, decimals),
    unidad: unit,
  });
}

/** Median and p10 to p90 of the snow covered area and the depth, as rows of a definition list. */
export default function SnowRange({ ranges, labels }: { ranges: SnowRanges; labels: Labels }) {
  const rows: Array<[string, string]> = [
    [labels.area, value(labels, ranges.area, "km²", 0)],
    [labels.meanDepth, value(labels, ranges.meanDepth, "cm", 0)],
    [labels.peakDepth, value(labels, ranges.peakDepth, "cm", 0)],
  ];
  return (
    <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-3 gap-y-1 text-small">
      {rows.map(([label, text]) => (
        <div key={label} className="contents">
          <dt className="text-text-muted">{t(label)}</dt>
          <dd className="tnum m-0">{text}</dd>
        </div>
      ))}
    </dl>
  );
}
