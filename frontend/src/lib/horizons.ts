export type HorizonId =
  | "plus24h"
  | "plus48h"
  | "plus72h"
  | "plus7d"
  | "plus1m";

export type Horizon = {
  id: HorizonId;
  short: string;
  label: string;
};

export const HORIZONS: Horizon[] = [
  { id: "plus24h", short: "24h", label: "+24 hours" },
  { id: "plus48h", short: "48h", label: "+48 hours" },
  { id: "plus72h", short: "72h", label: "+72 hours" },
  { id: "plus7d", short: "7d", label: "+7 days" },
  { id: "plus1m", short: "1mo", label: "+1 month" },
];

const ORDER: (HorizonId | null)[] = [
  null,
  "plus24h",
  "plus48h",
  "plus72h",
  "plus7d",
  "plus1m",
];

export function horizonById(id: HorizonId): Horizon | undefined {
  return HORIZONS.find((h) => h.id === id);
}

export function horizonToDate(
  horizon: HorizonId | null,
  now: Date = new Date(),
): Date {
  const d = new Date(now);
  if (horizon === null) return d;
  switch (horizon) {
    case "plus24h":
      d.setHours(d.getHours() + 24);
      break;
    case "plus48h":
      d.setHours(d.getHours() + 48);
      break;
    case "plus72h":
      d.setHours(d.getHours() + 72);
      break;
    case "plus7d":
      d.setDate(d.getDate() + 7);
      break;
    case "plus1m":
      d.setMonth(d.getMonth() + 1);
      break;
  }
  return d;
}

export function nextHorizon(h: HorizonId | null): HorizonId | null {
  const idx = ORDER.indexOf(h);
  if (idx < 0 || idx >= ORDER.length - 1) return h;
  return ORDER[idx + 1];
}

export function previousHorizon(h: HorizonId | null): HorizonId | null {
  const idx = ORDER.indexOf(h);
  if (idx <= 0) return h;
  return ORDER[idx - 1];
}

export function isFirstHorizon(h: HorizonId | null): boolean {
  return h === null;
}

export function isLastHorizon(h: HorizonId | null): boolean {
  return h === "plus1m";
}
