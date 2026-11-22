// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { repoFile } from "./test/dom";
import App from "./App";
import type { CatalogLayer } from "./components/Map";

// MapLibre needs WebGL: the stub writes the catalogue layers the shell passes, bottom to top.
vi.mock("./components/Map", () => ({
  default: (props: { catalogLayers: CatalogLayer[] }) => (
    <output data-testid="map-layers">
      {props.catalogLayers.map((l) => `${l.id}@${l.date}:${l.opacity}:${l.resampling}:${l.url}`).join("|")}
    </output>
  ),
}));

const CATALOG = "https://storage.example/nivosense/staging/catalog/index.json";
// The real scratch catalogue of the T0.4 evidence run (7 true colour entries, 24 Oct to 20 Nov 2026), served
// at the catalogue URL; the site's own static files as the static site serves them.
const FILES: Record<string, string> = {
  "/nivosense/staging/catalog/index.json": "frontend/src/test/fixtures/catalog-t04-evidence-98f90df.json",
  "/data/basins.geojson": "frontend/public/data/basins.geojson",
  "/data/webcams.json": "frontend/public/data/webcams.json",
  "/data/snow-model/manifest.json": "frontend/public/data/snow-model/manifest.json",
  "/weather/manifest.json": "frontend/public/weather/manifest.json",
};
const TILES = "pmtiles://https://storage.example/nivosense/staging/tiles/rgb/";

beforeEach(() => {
  vi.stubEnv("VITE_API_URL", "");
  vi.stubEnv("VITE_CATALOG_URL", CATALOG);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const file = FILES[new URL(String(input), "http://localhost/").pathname];
      return file ? new Response(repoFile(file), { status: 200 }) : new Response("", { status: 404 });
    }),
  );
  vi.spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => {
  vi.unstubAllEnvs();
  window.history.replaceState(null, "", "/");
});

const mapLayers = () => screen.getByTestId("map-layers").textContent;
// The whole shell renders under jsdom; on a busy machine the catalogue round trip takes a few seconds.
const SLOW = { timeout: 20_000 };

describe("App with a catalogue", () => {
  it("opens on the latest scene with the true colour on, and puts date and layers in the URL", async () => {
    render(<App />);
    await waitFor(() => expect(mapLayers()).toBe(`rgb@2026-11-20:1:linear:${TILES}2026-11-20-21285b710076ce5b.pmtiles`), SLOW);
    expect(window.location.search).toBe("?d=2026-11-20&l=rgb:100");
  });

  it("follows a shared link: its date, its opacity, and the nearest scene when the day has none", async () => {
    window.history.replaceState(null, "", "/?d=2026-11-12&l=rgb:40,swe:80");
    render(<App />);
    // 12 Nov has no true colour; 13 Nov is the nearest. SWE has no entry yet, so it is dropped from the link.
    await waitFor(() => expect(mapLayers()).toBe(`rgb@2026-11-13:0.4:linear:${TILES}2026-11-13-4fbe70cb122e4aff.pmtiles`), SLOW);
    expect(window.location.search).toBe("?d=2026-11-12&l=rgb:40");
    expect(screen.getByText(/Sin escena este día\. La más cercana: 13 nov 2026\./)).toBeTruthy();
  });

  it("switches a layer off and on from its row", async () => {
    render(<App />);
    await waitFor(() => expect(mapLayers()).not.toBe(""), SLOW);
    fireEvent.click(screen.getByRole("button", { name: "Ocultar Color real" }));
    expect(mapLayers()).toBe("");
    expect(window.location.search).toBe("?d=2026-11-20");
    fireEvent.click(screen.getByRole("button", { name: "Mostrar Color real" }));
    expect(mapLayers()).toContain("rgb@2026-11-20:1");
  });
});
