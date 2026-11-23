// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import "../test/dom";
import MetodoSection from "./MetodoSection";

describe("MetodoSection", () => {
  it("tells the evidence and its limits for the daily snow and the depth, with the numbers of the evaluation", () => {
    render(<MetodoSection />);
    const text = document.body.textContent ?? "";
    expect(screen.getByRole("region", { name: "Nieve diaria" })).toBeTruthy();
    expect(text).toContain("F1 de 0,74");
    expect(text).toContain("0,69");
    expect(text).toContain("cámara de Poqueira");
    expect(text).toContain("0,30 m");
    expect(text).toContain("factor de dos");
    expect(text).toContain("ERHIN");
    expect(text).toContain("UGR");
    expect(text).toContain("Cetursa");
    expect(text).toContain("Requiere medidas de campo para validarse");
  });

  it("makes no claim of validation and keeps no stale wording about assimilation or experimental models", () => {
    render(<MetodoSection />);
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/validad[oa]s? con medidas/i);
    expect(text).not.toMatch(/Modelo experimental/);
    expect(text).not.toMatch(/corrige su estado/);
    expect(text).not.toContain("2014");
  });
});
