import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchCatalog, parseCatalog } from "./catalog";

const entry = { layer: "rgb", date: "2026-11-10", status: "observed" };
const valid = {
  schema_version: 1,
  generated_at: "2026-11-22T00:00:00+00:00",
  entries_digest: "0".repeat(64),
  layers: { rgb: { dates: ["2026-11-10"], entries: [entry] } },
};

describe("parseCatalog", () => {
  it("accepts an index in the published shape", () => {
    expect(parseCatalog(valid).layers.rgb.entries[0].date).toBe("2026-11-10");
  });

  it("refuses another schema version, missing entries, bad dates and unknown statuses", () => {
    expect(() => parseCatalog({ ...valid, schema_version: 2 })).toThrow(/schema version/);
    expect(() => parseCatalog(null)).toThrow();
    expect(() => parseCatalog({ ...valid, layers: { rgb: { dates: [] } } })).toThrow(/no entries/);
    expect(() =>
      parseCatalog({ ...valid, layers: { rgb: { dates: [], entries: [{ ...entry, date: "10/11/2026" }] } } }),
    ).toThrow(/valid date/);
    expect(() =>
      parseCatalog({ ...valid, layers: { rgb: { dates: [], entries: [{ ...entry, status: "guessed" }] } } }),
    ).toThrow(/unknown status/);
  });
});

describe("fetchCatalog", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("treats a build without a catalogue URL as nothing published", async () => {
    await expect(fetchCatalog(undefined)).resolves.toEqual({ kind: "missing" });
  });

  it("treats a 404 as nothing published yet and other failures as errors", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("", { status: 404 })));
    await expect(fetchCatalog("https://example.test/catalog/index.json")).resolves.toEqual({ kind: "missing" });
    vi.stubGlobal("fetch", vi.fn(async () => new Response("", { status: 403 })));
    await expect(fetchCatalog("https://example.test/catalog/index.json")).rejects.toThrow("HTTP 403");
  });

  it("returns the parsed index", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(valid), { status: 200 })));
    const state = await fetchCatalog("https://example.test/catalog/index.json");
    expect(state.kind).toBe("ready");
  });
});
