import { describe, expect, it } from "vitest";
import { fechaConDia, fechaCorta, numero } from "./format";

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
