import { describe, expect, it } from "vitest";
import { fechaConDia, fechaCorta, mesInicial, mesLargo, numero } from "./format";

describe("Spanish formats from the copy deck", () => {
  it("formats short dates and weekdays", () => {
    expect(fechaCorta("2026-02-21")).toBe("21 feb 2026");
    expect(fechaConDia("2026-02-21")).toBe("sáb 21 feb 2026");
  });

  it("uses a decimal comma and a thin space only from 10 000", () => {
    expect(numero(319.24)).toBe("319,2");
    expect(numero(1250, 0)).toBe("1250");
    expect(numero(12500, 0)).toBe("12 500");
  });
});

describe("month labels for the timeline", () => {
  it("gives Spanish initials for the twelve months", () => {
    const initials = Array.from({ length: 12 }, (_, m) => mesInicial(`2026-${String(m + 1).padStart(2, "0")}-01`));
    expect(initials.join(" ")).toBe("E F M A M J J A S O N D");
  });

  it("keeps the full month name for tooltips", () => {
    expect(mesLargo("2026-01-01")).toBe("enero");
    expect(mesLargo("2026-09-01")).toBe("septiembre");
  });
});
