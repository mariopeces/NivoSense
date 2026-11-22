// @vitest-environment jsdom
import { useState } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { repoFile } from "../test/dom";
import type { CatalogIndex, CatalogState } from "../lib/catalog";
import { buildTimeline } from "../lib/timeline";
import Timeline from "./Timeline";

// Real Sentinel-2 L1C passes over the domain, from the T4.0 pass list (Earth Search), used as the dates of
// observed entries. Nothing here is published; the test only needs dates that exist.
const PASSES = new Set(
  (JSON.parse(repoFile("docs/design/mockups/data/s2_passes.json")).passes as Array<{ date: string }>).map((p) => p.date),
);
const DATES = ["2026-02-11", "2026-02-21", "2026-02-23"];
for (const date of DATES) if (!PASSES.has(date)) throw new Error(`${date} is not a pass in s2_passes.json`);

const INDEX: CatalogIndex = {
  schema_version: 1,
  generated_at: "2026-11-22T00:00:00+00:00",
  layers: {
    snow_obs: {
      dates: DATES,
      entries: DATES.map((date) => ({
        layer: "snow_obs",
        date,
        status: "observed" as const,
        cog: `layers/snow_obs/2026/${date}.tif`,
        pmtiles: `tiles/snow_obs/${date}.pmtiles`,
        bounds: [-3.6, 36.9, -2.6, 37.3] as [number, number, number, number],
        resolution_m: 20,
        bands: ["class"],
        units: ["1"],
        source_ids: [date],
      })),
    },
  },
};
const TODAY = "2026-03-01";
const MODEL = buildTimeline(INDEX, TODAY);

function Harness({ start = "2026-02-21", catalog = { kind: "ready", index: INDEX } as CatalogState }) {
  const [date, setDate] = useState<string | null>(start);
  const model = catalog.kind === "ready" ? buildTimeline(catalog.index, TODAY) : null;
  return (
    <>
      <Timeline catalog={catalog} model={model} selectedDate={date} onChange={setDate} onRetry={() => {}} mobile={false} />
      <output data-testid="date">{date ?? "none"}</output>
    </>
  );
}

const current = () => screen.getByTestId("date").textContent;
const slider = () => screen.getByRole("slider", { name: "Fecha del mapa" });
const button = (name: string | RegExp) => screen.getByRole("button", { name });

afterEach(() => vi.useRealTimers());

describe("Timeline", () => {
  it("covers every day from the season start to today", () => {
    render(<Harness />);
    expect(MODEL?.days[0].date).toBe("2025-10-01");
    expect(slider().getAttribute("aria-valuemax")).toBe(String((MODEL?.days.length ?? 0) - 1));
    expect(slider().getAttribute("aria-valuetext")).toBe("sáb 21 feb 2026: Observado");
  });

  it("always shows Hoy and the forecast slot, which says it is not published yet without forecasts", () => {
    render(<Harness />);
    expect(screen.getByText("Hoy")).toBeTruthy();
    const slot = screen.getByText("Previsión", { selector: "span[title]" });
    expect(slot.getAttribute("title")).toContain("Previsión: aún no se publica");
  });

  it("keeps Última and the calendar in place, disabled, when there is nothing to show", () => {
    render(<Timeline catalog={{ kind: "missing" }} model={null} selectedDate={null} onChange={() => {}} onRetry={() => {}} mobile={false} />);
    expect((button(/Última/) as HTMLButtonElement).disabled).toBe(true);
    expect((button("Elegir en el calendario") as HTMLButtonElement).disabled).toBe(true);
  });

  it("steps one day with the arrows and one pass with Shift, Home and End go to the ends", () => {
    render(<Harness />);
    fireEvent.keyDown(slider(), { key: "ArrowRight" });
    expect(current()).toBe("2026-02-22");
    expect(slider().getAttribute("aria-valuetext")).toBe("dom 22 feb 2026: Pendiente");
    fireEvent.keyDown(slider(), { key: "ArrowRight", shiftKey: true });
    expect(current()).toBe("2026-02-23");
    fireEvent.keyDown(slider(), { key: "ArrowLeft", shiftKey: true });
    fireEvent.keyDown(slider(), { key: "ArrowLeft", shiftKey: true });
    expect(current()).toBe("2026-02-11");
    fireEvent.keyDown(slider(), { key: "Home" });
    expect(current()).toBe("2025-10-01");
    fireEvent.keyDown(slider(), { key: "End" });
    expect(current()).toBe(TODAY);
  });

  it("steps through dates with data with the buttons and jumps to the latest", () => {
    render(<Harness start="2026-02-15" />);
    fireEvent.click(button("Fecha siguiente con datos"));
    expect(current()).toBe("2026-02-21");
    fireEvent.click(button("Fecha anterior con datos"));
    expect(current()).toBe("2026-02-11");
    expect((button("Fecha anterior con datos") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(button(/Última/));
    expect(current()).toBe("2026-02-23");
    expect((button(/Última/) as HTMLButtonElement).disabled).toBe(true);
  });

  it("plays one date with data per frame and stops at the last", () => {
    vi.useFakeTimers();
    render(<Harness start="2026-02-11" />);
    fireEvent.click(button("Reproducir"));
    expect(button("Pausar")).toBeTruthy();
    act(() => vi.advanceTimersByTime(799));
    expect(current()).toBe("2026-02-11");
    act(() => vi.advanceTimersByTime(1));
    expect(current()).toBe("2026-02-21");
    act(() => vi.advanceTimersByTime(800));
    expect(current()).toBe("2026-02-23");
    act(() => vi.advanceTimersByTime(800));
    expect(current()).toBe("2026-02-23");
    expect((button("Reproducir") as HTMLButtonElement).disabled).toBe(true);
  });

  it("offers in the calendar only the days that have a product and returns focus on pick", () => {
    render(<Harness />);
    fireEvent.click(button("Elegir en el calendario"));
    const enabled = screen
      .getAllByRole("button")
      .filter((b) => /de febrero de 2026/.test(b.getAttribute("aria-label") ?? "") && !(b as HTMLButtonElement).disabled)
      .map((b) => b.getAttribute("aria-label"));
    expect(enabled).toEqual([
      "miércoles 11 de febrero de 2026: Observado",
      "sábado 21 de febrero de 2026: Observado",
      "lunes 23 de febrero de 2026: Observado",
    ]);
    fireEvent.click(button("miércoles 11 de febrero de 2026: Observado"));
    expect(current()).toBe("2026-02-11");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement?.getAttribute("aria-label")).toBe("Elegir en el calendario");
  });

  it("says why it is empty, shows the error with a retry, and renders nothing while loading", () => {
    const onRetry = vi.fn();
    const { rerender, container } = render(
      <Timeline catalog={{ kind: "missing" }} model={null} selectedDate={null} onChange={() => {}} onRetry={onRetry} mobile={false} />,
    );
    expect(screen.getByText("Aún no hay escenas publicadas.")).toBeTruthy();
    expect(screen.queryByRole("slider")).toBeNull();
    rerender(<Timeline catalog={{ kind: "error" }} model={null} selectedDate={null} onChange={() => {}} onRetry={onRetry} mobile={false} />);
    expect(screen.getByRole("alert").textContent).toContain("No se pudo cargar el catálogo");
    fireEvent.click(button("Reintentar"));
    expect(onRetry).toHaveBeenCalledOnce();
    rerender(<Timeline catalog={{ kind: "loading" }} model={null} selectedDate={null} onChange={() => {}} onRetry={onRetry} mobile={false} />);
    expect(container.innerHTML).toBe("");
  });
});
