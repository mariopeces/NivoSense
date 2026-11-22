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
    const swe = within(row("Equivalente en agua (SWE)"));
    expect((swe.getByRole("button", { name: "Mostrar Equivalente en agua (SWE)" }) as HTMLButtonElement).disabled).toBe(true);
    expect(swe.getByText("Pendiente")).toBeTruthy();
    expect(swe.getByText("SWE (mm) · Menos de 5 mm: sin color")).toBeTruthy();
    expect((swe.getByRole("slider") as HTMLInputElement).disabled).toBe(true);
    // The observed-snow legend lists every class of the ramp.
    const obs = within(row("Nieve observada"));
    for (const cls of RAMPS.snow_cover_observed.classes) expect(obs.getByText(cls.label_es)).toBeTruthy();
  });

  it("labels a modelled layer as an experimental model with its caveat and lets it be switched on", () => {
    const modelled = (layer: string, unit: string) => ({
      dates: ["2026-11-10"],
      entries: [
        {
          layer,
          date: "2026-11-10",
          status: "modelled" as const,
          cog: `layers/${layer}/2026/x.tif`,
          pmtiles: `tiles/${layer}/x.pmtiles`,
          bounds: [-3.6, 36.9, -2.6, 37.3] as [number, number, number, number],
          resolution_m: 100,
          bands: [layer],
          units: [unit],
          source_ids: ["open-meteo:ecmwf_ifs"],
        },
      ],
    });
    const index = parseCatalog({
      schema_version: 1,
      generated_at: "2026-11-22T00:00:00.000+00:00",
      layers: { swe: modelled("swe", "mm"), snow_depth: modelled("snow_depth", "m") },
    });
    render(<Harness catalog={{ kind: "ready", index }} />);
    const swe = within(row("Equivalente en agua (SWE)"));
    expect(swe.getByText("Modelo experimental.")).toBeTruthy();
    expect(swe.getByText(/corregida con cada imagen despejada de Sentinel-2/)).toBeTruthy();
    expect(swe.queryByText("Pendiente")).toBeNull();
    fireEvent.click(swe.getByRole("button", { name: "Mostrar Equivalente en agua (SWE)" }));
    expect(state()).toBe("2026-11-10 swe:100");
    expect(within(row("Espesor de nieve")).getByText("Modelo experimental.")).toBeTruthy();
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
    expect(screen.getAllByText("Pendiente")).toHaveLength(5);
    rerender(<Harness catalog={{ kind: "error" }} onRetry={onRetry} />);
    expect(screen.getByRole("alert").textContent).toContain("No se pudo cargar el catálogo");
    fireEvent.click(screen.getByRole("button", { name: /Reintentar/ }));
    expect(onRetry).toHaveBeenCalledOnce();
    rerender(<Harness catalog={{ kind: "loading" }} />);
    expect(screen.getAllByRole("status").some((el) => el.getAttribute("aria-busy") === "true")).toBe(true);
    expect(screen.queryByText("Color real")).toBeNull();
  });
});
