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

export function horizonById(id: HorizonId): Horizon | undefined {
  return HORIZONS.find((h) => h.id === id);
}
