// The part of catalog/index.json (pipelines/catalog/schema.json) the site reads. The index is the only
// place the site learns which products exist.
export type CatalogStatus = "observed" | "gapfilled" | "modelled" | "forecast";

export type CatalogEntry = {
  layer: string;
  date: string;
  status: CatalogStatus;
  cog: string;
  pmtiles: string;
  bounds: [number, number, number, number];
  resolution_m: number;
  bands: string[];
  units: string[];
  source_ids: string[];
};

export type CatalogIndex = {
  schema_version: 1;
  generated_at: string;
  layers: Record<string, { dates: string[]; entries: CatalogEntry[] }>;
};

export type CatalogState =
  | { kind: "loading" }
  // No catalogue published yet (no URL configured, or the object does not exist).
  | { kind: "missing" }
  | { kind: "error" }
  | { kind: "ready"; index: CatalogIndex };

const STATUSES = new Set<string>(["observed", "gapfilled", "modelled", "forecast"]);
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export function parseCatalog(payload: unknown): CatalogIndex {
  if (!payload || typeof payload !== "object") throw new Error("Catalogue is not an object");
  const index = payload as Record<string, unknown>;
  if (index.schema_version !== 1) {
    throw new Error(`Unsupported catalogue schema version ${String(index.schema_version)}`);
  }
  if (!index.layers || typeof index.layers !== "object") throw new Error("Catalogue has no layers");
  for (const [layer, value] of Object.entries(index.layers as Record<string, unknown>)) {
    const entries = (value as { entries?: unknown })?.entries;
    if (!Array.isArray(entries)) throw new Error(`Layer ${layer} has no entries`);
    for (const entry of entries as Array<Record<string, unknown>>) {
      if (typeof entry?.date !== "string" || !ISO_DATE.test(entry.date)) {
        throw new Error(`Layer ${layer} has an entry without a valid date`);
      }
      if (typeof entry.status !== "string" || !STATUSES.has(entry.status)) {
        throw new Error(`Layer ${layer} ${entry.date} has an unknown status`);
      }
    }
  }
  return payload as CatalogIndex;
}

export async function fetchCatalog(url: string | undefined, signal?: AbortSignal): Promise<CatalogState> {
  if (!url) return { kind: "missing" };
  const response = await fetch(url, { signal, cache: "no-cache" });
  // GCS answers 404 for an object that was never written: nothing has been published yet, which is not a
  // failure. Any other status is.
  if (response.status === 404) return { kind: "missing" };
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return { kind: "ready", index: parseCatalog(await response.json()) };
}
