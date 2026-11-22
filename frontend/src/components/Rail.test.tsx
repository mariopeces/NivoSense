// @vitest-environment jsdom
import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import "../test/dom";
import Rail, { SECTIONS, sectionAfterKey, type Section } from "./Rail";
import type { Basemap } from "../lib/basemaps";

function Harness() {
  const [section, setSection] = useState<Section>("nieve");
  const [open, setOpen] = useState(true);
  const [basemap, setBasemap] = useState<Basemap>("claro");
  const [terrain, setTerrain] = useState(false);
  return (
    <>
      <Rail
        section={section}
        onSection={setSection}
        panelOpen={open}
        onTogglePanel={() => setOpen((v) => !v)}
        basemap={basemap}
        onBasemap={setBasemap}
        terrain={terrain}
        onToggleTerrain={() => setTerrain((v) => !v)}
      />
      <output data-testid="state">{`${section}|${open}|${basemap}|${terrain}`}</output>
    </>
  );
}

const state = () => screen.getByTestId("state").textContent;
const selectedTab = () => screen.getByRole("tab", { selected: true });

describe("sectionAfterKey", () => {
  it("steps with the arrows, wraps at both ends and jumps with Home and End", () => {
    expect(SECTIONS.map((s) => s.id)).toEqual(["nieve", "agua", "webcams", "meteo", "metodo"]);
    expect(sectionAfterKey("nieve", "ArrowDown")).toBe("agua");
    expect(sectionAfterKey("nieve", "ArrowRight")).toBe("agua");
    expect(sectionAfterKey("agua", "ArrowUp")).toBe("nieve");
    expect(sectionAfterKey("agua", "ArrowLeft")).toBe("nieve");
    expect(sectionAfterKey("nieve", "ArrowUp")).toBe("metodo");
    expect(sectionAfterKey("metodo", "ArrowDown")).toBe("nieve");
    expect(sectionAfterKey("meteo", "Home")).toBe("nieve");
    expect(sectionAfterKey("agua", "End")).toBe("metodo");
    expect(sectionAfterKey("agua", "Enter")).toBeNull();
  });
});

describe("Rail", () => {
  it("is a tablist with one selected, focusable tab per section", () => {
    render(<Harness />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual(["Nieve", "Agua", "Webcams", "Meteo", "Método"]);
    expect(selectedTab()).toHaveProperty("textContent", "Nieve");
    expect(tabs.filter((tab) => tab.tabIndex === 0)).toHaveLength(1);
  });

  it("switches section on click and on arrow keys, moving focus with the selection", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("tab", { name: "Webcams" }));
    expect(state()).toMatch(/^webcams\|/);
    fireEvent.keyDown(selectedTab(), { key: "ArrowDown" });
    expect(state()).toMatch(/^meteo\|/);
    expect(document.activeElement).toBe(screen.getByRole("tab", { name: "Meteo" }));
    fireEvent.keyDown(selectedTab(), { key: "End" });
    fireEvent.keyDown(selectedTab(), { key: "ArrowDown" });
    expect(state()).toMatch(/^nieve\|/);
  });

  it("collapses and reopens the panel from the rail foot", () => {
    render(<Harness />);
    const toggle = screen.getByRole("button", { name: "Ocultar" });
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(toggle);
    expect(state()).toMatch(/^nieve\|false\|/);
    const reopen = screen.getByRole("button", { name: "Mostrar" });
    expect(reopen.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(reopen);
    expect(state()).toMatch(/^nieve\|true\|/);
  });

  it("switches the basemap from its popover and closes it with Escape", () => {
    render(<Harness />);
    const button = screen.getByRole("button", { name: "Mapa" });
    fireEvent.click(button);
    fireEvent.click(screen.getByLabelText("Ortofoto PNOA (IGN)"));
    expect(state()).toMatch(/\|ortofoto\|/);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(button);
  });

  it("toggles 3D terrain", () => {
    render(<Harness />);
    const button = screen.getByRole("button", { name: "3D" });
    fireEvent.click(button);
    expect(state()).toMatch(/\|true$/);
    expect(button.getAttribute("aria-pressed")).toBe("true");
  });
});
