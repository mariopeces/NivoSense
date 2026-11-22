// @vitest-environment jsdom
import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { repoFile } from "../test/dom";
import DateBar, { type Scene } from "./DateBar";

// Three real Sentinel-2 L1C passes over the domain, from the T4.0 pass list (Earth Search). The last one is
// flagged as a prediction only to exercise the Previsión badge. The bar must never offer any other day.
const PASSES = new Set(
  (JSON.parse(repoFile("docs/design/mockups/data/s2_passes.json")).passes as Array<{ date: string }>).map((p) => p.date),
);
const SCENES: Scene[] = ["2026-02-11", "2026-02-21", "2026-02-23"].map((date, i) => {
  if (!PASSES.has(date)) throw new Error(`${date} is not a pass in s2_passes.json`);
  return { date, isPrediction: i === 2 };
});

function Harness({ scenes = SCENES, start = "2026-02-21" }: { scenes?: Scene[]; start?: string | null }) {
  const [date, setDate] = useState<string | null>(start);
  return (
    <>
      <DateBar scenes={scenes} loading={false} selectedDate={date} onChange={setDate} />
      <output data-testid="date">{date ?? "none"}</output>
    </>
  );
}

const current = () => screen.getByTestId("date").textContent;
const prev = () => screen.getByRole("button", { name: "Fecha anterior con datos" });
const next = () => screen.getByRole("button", { name: "Fecha siguiente con datos" });

describe("DateBar", () => {
  it("steps only through scene dates and stops at both ends", () => {
    render(<Harness />);
    expect(screen.getByText("sáb 21 feb 2026")).toBeTruthy();
    fireEvent.click(next());
    expect(current()).toBe("2026-02-23");
    expect(screen.getByText("Previsión")).toBeTruthy();
    expect((next() as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(prev());
    fireEvent.click(prev());
    expect(current()).toBe("2026-02-11");
    expect((prev() as HTMLButtonElement).disabled).toBe(true);
  });

  it("jumps to the latest scene", () => {
    render(<Harness start="2026-02-11" />);
    fireEvent.click(screen.getByRole("button", { name: /Última/ }));
    expect(current()).toBe("2026-02-23");
  });

  it("offers in the calendar only the days that have a scene", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Elegir en el calendario" }));
    const days = screen.getAllByRole("button").filter((b) => /de (enero|febrero|marzo) de 2026$/.test(b.getAttribute("aria-label") ?? ""));
    const enabled = days.filter((b) => !(b as HTMLButtonElement).disabled).map((b) => b.getAttribute("aria-label"));
    expect(enabled).toEqual([
      "miércoles 11 de febrero de 2026",
      "sábado 21 de febrero de 2026",
      "lunes 23 de febrero de 2026",
    ]);
    fireEvent.click(screen.getByRole("button", { name: "miércoles 11 de febrero de 2026" }));
    expect(current()).toBe("2026-02-11");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("says why it is empty when there are no scenes, and renders nothing while loading", () => {
    render(<Harness scenes={[]} start={null} />);
    expect(screen.getByText("Aún no hay escenas publicadas.")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
    cleanupAndLoading();
  });
});

function cleanupAndLoading() {
  const { container } = render(<DateBar scenes={SCENES} loading selectedDate={null} onChange={() => {}} />);
  expect(container.innerHTML).toBe("");
}
