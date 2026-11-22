// @vitest-environment jsdom
import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import "../test/dom";
import Panel, { NEXT_SHEET, type SheetHeight } from "./Panel";
import type { Section } from "./Rail";

function Harness({ section = "nieve", open = true }: { section?: Section; open?: boolean }) {
  const [sheet, setSheet] = useState<SheetHeight>("peek");
  return (
    <>
      <Panel section={section} open={open} sheet={sheet} onSheet={setSheet}>
        <p>contenido</p>
      </Panel>
      <output data-testid="sheet">{sheet}</output>
    </>
  );
}

describe("Panel", () => {
  it("cycles the bottom sheet peek, half, full and back to peek", () => {
    expect(NEXT_SHEET).toEqual({ peek: "half", half: "full", full: "peek" });
    render(<Harness />);
    const handle = screen.getByRole("button", { name: "Arrastra para ampliar o reducir" });
    const seen = [screen.getByTestId("sheet").textContent];
    for (let i = 0; i < 3; i += 1) {
      fireEvent.click(handle);
      seen.push(screen.getByTestId("sheet").textContent);
    }
    expect(seen).toEqual(["peek", "half", "full", "peek"]);
  });

  it("shows the eyebrow, title and subtitle of each section from the copy deck", () => {
    const { rerender } = render(<Harness section="agua" />);
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("Cuencas");
    expect(screen.getByText("Agua")).toBeTruthy();
    rerender(<Harness section="metodo" />);
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe("Cómo se hace cada capa");
  });

  it("is a tab panel labelled by its rail tab, marked collapsed when closed", () => {
    const { rerender } = render(<Harness section="webcams" />);
    const panel = screen.getByRole("tabpanel", { hidden: true });
    expect(panel.getAttribute("aria-labelledby")).toBe("tab-webcams");
    expect(panel.classList.contains("is-collapsed")).toBe(false);
    rerender(<Harness section="webcams" open={false} />);
    expect(panel.classList.contains("is-collapsed")).toBe(true);
  });
});
