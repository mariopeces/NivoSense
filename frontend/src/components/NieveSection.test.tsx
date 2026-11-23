// @vitest-environment jsdom
import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import "../test/dom";
import fixture from "../test/fixtures/catalog-t04-evidence-98f90df.json";
import { parseCatalog, type CatalogState } from "../lib/catalog";
import { RAMPS } from "../lib/layers";
import type { VisibleLayers } from "../lib/urlState";
import NieveSection from "./NieveSection";

// The real scratch catalogue of the T0.4 evidence run: 7 true colour entries, no snow layer yet.
const READY: CatalogState = { kind: "ready", index: parseCatalog(fixture) };

function Harness({ catalog = READY, start = "2026-11-10", layers = [] as VisibleLayers, onMethod = () => {}, onRetry = () => {} }) {
  const [date, setDate] = useState(start);
  const [visible, setVisible] = useState<VisibleLayers>(layers);
  return (
    <>
      <NieveSection
        catalog={catalog}
        date={date}
        visible={visible}
        onToggle={(id) =>
          setVisible((v) => (v.some((l) => l.id === id) ? v.filter((l) => l.id !== id) : [...v, { id, opacity: 100 }]))
        }
        onOpacity={(id, opacity) => setVisible((v) => v.map((l) => (l.id === id ? { ...l, opacity } : l)))}
        onDate={setDate}
        onMethod={onMethod}
        onRetry={onRetry}
      />
      <output data-testid="state">{`${date} ${visible.map((l) => `${l.id}:${l.opacity}`).join(",")}`}</output>
    </>
  );
}

const state = () => screen.getByTestId("state").textContent;
const row = (name: string) => screen.getByText(name, { selector: "p" }).closest("div.mb-2") as HTMLElement;

describe("NieveSection", () => {
  it("has one row per layer, pending ones keep their legend but cannot be switched on", () => {
    render(<Harness />);
    for (const name of ["Nieve observada", "Nieve diaria", "Equivalente en agua (SWE)", "Espesor de nieve", "Color real"]) {
      expect(row(name)).toBeTruthy();
    }
    const daily = within(row("Nieve diaria"));
    expect((daily.getByRole("button", { name: "Mostrar Nieve diaria" }) as HTMLButtonElement).disabled).toBe(true);
    expect(daily.getByText("Pendiente")).toBeTruthy();
    expect((daily.getByRole("slider") as HTMLInputElement).disabled).toBe(true);
    // The observed-snow legend lists every class of the ramp.
    const obs = within(row("Nieve observada"));
    for (const cls of RAMPS.snow_cover_observed.classes) expect(obs.getByText(cls.label_es)).toBeTruthy();
  });

  const depthEntry = (scores: Record<string, number> = {}) => ({
    layer: "snow_depth",
    date: "2026-11-10",
    status: "modelled" as const,
    cog: "layers/snow_depth/2026/x.tif",
    pmtiles: "tiles/snow_depth/x.pmtiles",
    bounds: [-3.6, 36.9, -2.6, 37.3] as [number, number, number, number],
    resolution_m: 100,
    bands: ["depth_p50", "depth_p10", "depth_p90"],
    units: ["m", "m", "m"],
    source_ids: ["open-meteo:ecmwf_ifs"],
    qa: { flags: ["prior_ensemble"], scores },
  });
  const catalogWith = (layers: Record<string, unknown[]>): CatalogState => ({
    kind: "ready",
    index: parseCatalog({
      schema_version: 1,
      generated_at: "2026-11-22T00:00:00.000+00:00",
      layers: Object.fromEntries(
        Object.entries(layers).map(([id, entries]) => [id, { dates: (entries as { date: string }[]).map((e) => e.date), entries }]),
      ),
    }),
  });

  it("labels the depth as a model estimate (median of an ensemble, one camera, a factor of two) and lets it be switched on", () => {
    render(<Harness catalog={catalogWith({ snow_depth: [depthEntry()] })} />);
    const depth = within(row("Espesor de nieve"));
    expect(depth.getByText("Estimación del modelo.")).toBeTruthy();
    expect(depth.getByText(/mediana de un conjunto de simulaciones/)).toBeTruthy();
    expect(depth.getByText(/una sola cámara \(2010 a 2013\).*factor de dos/)).toBeTruthy();
    expect(screen.queryByText(/experimental/i)).toBeNull();
    expect(screen.queryByText(/validad/i)).toBeNull();
    expect(depth.queryByText("Pendiente")).toBeNull();
    expect(depth.getByText("Modelado")).toBeTruthy();
    fireEvent.click(depth.getByRole("button", { name: "Mostrar Espesor de nieve" }));
    expect(state()).toBe("2026-11-10 snow_depth:100");
  });

  it("shows the p10 to p90 range of the depth in the layer information, from the qa scores", () => {
    const scores = {
      domain_snow_area_km2_p10: 200,
      domain_snow_area_km2_p50: 310.4,
      domain_snow_area_km2_p90: 450,
      domain_depth_mean_m_p10: 0.12,
      domain_depth_mean_m_p50: 0.31,
      domain_depth_mean_m_p90: 0.62,
      domain_depth_peak_m_p10: 0.9,
      domain_depth_peak_m_p50: 1.9,
      domain_depth_peak_m_p90: 3.4,
    };
    render(<Harness catalog={catalogWith({ snow_depth: [depthEntry(scores)] })} />);
    fireEvent.click(screen.getByRole("button", { name: "Información de Espesor de nieve" }));
    const dialog = within(screen.getByRole("dialog", { name: "Sobre esta capa: Espesor de nieve" }));
    expect(dialog.getByText("Rango del conjunto (p10 a p90)")).toBeTruthy();
    expect(dialog.getByText("310 km² (de 200 a 450)")).toBeTruthy();
    expect(dialog.getByText("31 cm (de 12 a 62)")).toBeTruthy();
    expect(dialog.getByText("190 cm (de 90 a 340)")).toBeTruthy();
  });

  it("offers the daily snow once it has entries and says whether the day has an image", () => {
    const entry = (flags: string[]) => ({
      ...depthEntry(),
      layer: "snow_gapfill",
      status: "gapfilled" as const,
      resolution_m: 20,
      bands: ["snow_probability", "obs_age_days"],
      qa: { flags, scores: {} },
    });
    const { rerender } = render(<Harness catalog={catalogWith({ snow_gapfill: [entry(["observation_used"])] })} />);
    const daily = () => within(row("Nieve diaria"));
    expect(daily().queryByText("Próximamente")).toBeNull();
    expect(daily().getByText(/Con imagen despejada de Sentinel-2 este día/)).toBeTruthy();
    expect(daily().getByText("Rellenado")).toBeTruthy();
    expect((daily().getByRole("button", { name: "Mostrar Nieve diaria" }) as HTMLButtonElement).disabled).toBe(false);
    rerender(<Harness catalog={catalogWith({ snow_gapfill: [entry(["prior_ensemble"])] })} />);
    expect(daily().getByText("Sin imagen despejada este día: probabilidad del modelo.")).toBeTruthy();
    rerender(<Harness catalog={catalogWith({ snow_gapfill: [entry(["observation_used", "quality_check_failed"])] })} />);
    expect(daily().getByText("El modelo y la imagen de este día discrepan más de lo habitual.")).toBeTruthy();
  });

  it("says a daily layer has no data for a day outside its record, instead of showing another day", () => {
    render(<Harness catalog={catalogWith({ snow_depth: [depthEntry()] })} start="2026-11-12" />);
    expect(within(row("Espesor de nieve")).getByText("Esta capa no tiene dato para este día.")).toBeTruthy();
  });

  it("switches the true colour on, sets its opacity and shows its scene date and status", () => {
    render(<Harness />);
    const rgb = within(row("Color real"));
    expect(rgb.getByText("Sentinel-2 L1C · 10 m")).toBeTruthy();
    expect(rgb.getByText("Escena del 10 nov 2026")).toBeTruthy();
    expect(rgb.getByText("Observado")).toBeTruthy();
    fireEvent.click(rgb.getByRole("button", { name: "Mostrar Color real" }));
    expect(state()).toBe("2026-11-10 rgb:100");
    expect(rgb.getByRole("button", { name: "Ocultar Color real" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.change(rgb.getByRole("slider"), { target: { value: "60" } });
    expect(state()).toBe("2026-11-10 rgb:60");
    expect(rgb.getByRole("slider").getAttribute("aria-valuetext")).toBe("60 %");
  });

  it("says when the layer has no scene that day and goes to the nearest one", () => {
    render(<Harness start="2026-11-11" layers={[{ id: "rgb", opacity: 100 }]} />);
    const rgb = within(row("Color real"));
    expect(rgb.getByText(/Sin escena este día\. La más cercana: 10 nov 2026\./)).toBeTruthy();
    fireEvent.click(rgb.getByRole("button", { name: "Ir al 10 nov 2026" }));
    expect(state()).toBe("2026-11-10 rgb:100");
    expect(rgb.getByText("Escena del 10 nov 2026")).toBeTruthy();
  });

  it("opens the info popover with source, resolution, real date, status and scene ids, and closes it with Esc", () => {
    const onMethod = vi.fn();
    render(<Harness onMethod={onMethod} />);
    const info = screen.getByRole("button", { name: "Información de Color real" });
    fireEvent.click(info);
    const dialog = within(screen.getByRole("dialog", { name: "Sobre esta capa: Color real" }));
    expect(dialog.getByText("Sentinel-2 L1C")).toBeTruthy();
    expect(dialog.getByText("10 m")).toBeTruthy();
    expect(dialog.getByText("Cada pasada")).toBeTruthy();
    expect(dialog.getByText("10 nov 2026")).toBeTruthy();
    const entry = READY.kind === "ready" ? READY.index.layers.rgb.entries.find((e) => e.date === "2026-11-10") : undefined;
    for (const id of entry?.source_ids ?? []) expect(dialog.getByText(id)).toBeTruthy();
    fireEvent.click(dialog.getByRole("button", { name: "Ver el método" }));
    expect(onMethod).toHaveBeenCalledOnce();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(info);
  });

  it("gives a layer the catalogue lists but the site does not know a row of its own", () => {
    const index = parseCatalog(fixture);
    const wet = { ...index.layers.rgb.entries[0], layer: "wet_snow", resolution_m: 20 };
    const catalog: CatalogState = { kind: "ready", index: { ...index, layers: { ...index.layers, wet_snow: { dates: [wet.date], entries: [wet] } } } };
    render(<Harness catalog={catalog} start={wet.date} />);
    fireEvent.click(within(row("wet_snow")).getByRole("button", { name: "Mostrar wet_snow" }));
    expect(state()).toContain("wet_snow:100");
  });

  it("is honest without a catalogue: notice and every row pending; error with a retry; skeleton while loading", () => {
    const onRetry = vi.fn();
    const { rerender } = render(<Harness catalog={{ kind: "missing" }} />);
    expect(screen.getByText("Aún no hay escenas publicadas")).toBeTruthy();
    expect(screen.getAllByText("Pendiente")).toHaveLength(4);
    rerender(<Harness catalog={{ kind: "error" }} onRetry={onRetry} />);
    expect(screen.getByRole("alert").textContent).toContain("No se pudo cargar el catálogo");
    fireEvent.click(screen.getByRole("button", { name: /Reintentar/ }));
    expect(onRetry).toHaveBeenCalledOnce();
    rerender(<Harness catalog={{ kind: "loading" }} />);
    expect(screen.getAllByRole("status").some((el) => el.getAttribute("aria-busy") === "true")).toBe(true);
    expect(screen.queryByText("Color real")).toBeNull();
  });

  it("locks the SWE with its reason, whatever the catalogue holds, and never lists its entries", () => {
    const v1 = { ...depthEntry(), layer: "swe", bands: ["swe"], units: ["mm"] };
    render(<Harness catalog={catalogWith({ swe: [v1], snow_depth: [depthEntry()] })} />);
    const swe = row("Equivalente en agua (SWE)");
    const toggle = within(swe).getByRole("button", { name: "Equivalente en agua (SWE): Próximamente" }) as HTMLButtonElement;
    expect(toggle.disabled).toBe(true);
    expect(swe.closest("[data-locked]") ?? swe.getAttribute("data-locked")).toBeTruthy();
    expect(within(swe).getByText("Requiere medidas de campo para validarse")).toBeTruthy();
    expect(within(swe).getAllByText("Próximamente").length).toBeGreaterThan(0);
    expect(within(swe).queryByText(/Escena|Calculado para/)).toBeNull();
    expect(within(swe).queryByText("Modelado")).toBeNull();
  });
});
