import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import deck from "../../../docs/design/copy.es.json";
import { t } from "./copy";
import { BASEMAPS } from "./basemaps";
import { WEATHER_VARIABLES } from "./weather";
import { SECTIONS } from "../components/Rail";
import { ROWS } from "../components/NieveSection";
import { LAYERS } from "../components/MetodoSection";
import { STATUSES } from "../components/ui";

// t() throws on a missing key and nothing catches it at render, so every key the interface can ask for must
// exist. Composed keys are checked by expanding each template over the values it can take at render.
const sections = SECTIONS.map((s) => s.id);
const rowCopy = ROWS.map((r) => r.copy);
const TEMPLATES: Record<string, readonly string[]> = {
  "rail.${item.id}": sections,
  "rail.tooltip_${item.id}": sections,
  "panel.${section}.eyebrow": sections,
  "panel.${section}.titulo": sections,
  "panel.${section}.subtitulo": sections,
  "estado.${status}": STATUSES,
  "estado.tooltip_${status}": STATUSES,
  "capa.${row.copy}.nombre": rowCopy,
  "capa.${row.copy}.fuente": rowCopy,
  "capa.${row.copy}.resolucion": rowCopy,
  "capa.${layer}.nombre": LAYERS,
  "capa.${layer}.fuente": LAYERS,
  "capa.${layer}.resolucion": LAYERS,
  "capa.${layer}.cadencia": LAYERS,
  "capa.${layer}.descripcion": LAYERS,
  "mapa_base.${id}": BASEMAPS,
  "meteo.${item}": WEATHER_VARIABLES,
};

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const file = path.join(dir, name);
    if (statSync(file).isDirectory()) return name === "test" ? [] : sources(file);
    return /\.tsx?$/.test(name) && !name.includes(".test.") ? [file] : [];
  });
}

const code = sources(path.resolve(__dirname, "..")).map((file) => readFileSync(file, "utf8")).join("\n");
const SECTIONS_OF_DECK = Object.keys(deck).filter((key) => !key.startsWith("$") && key !== "formats");

describe("copy deck", () => {
  it("fills braced tokens", () => {
    expect(t("fila_capa.mostrar", { capa: "SWE" })).toBe("Mostrar SWE");
  });

  it("has every key written as a string anywhere in the interface (t() calls, ternaries, lookup tables)", () => {
    const literal = new RegExp(`["'](?:${SECTIONS_OF_DECK.join("|")})\\.[a-z0-9_.]+["']`, "g");
    const keys = new Set([...code.matchAll(literal)].map((m) => m[0].slice(1, -1)));
    expect(keys.size).toBeGreaterThan(80);
    const missing = [...keys].filter((key) => {
      try {
        t(key);
        return false;
      } catch {
        return true;
      }
    });
    expect(missing).toEqual([]);
  });

  it("knows every template key the code composes, and every expansion exists", () => {
    const used = new Set([...code.matchAll(/\bt\(\s*`([^`]*)`/g)].map((m) => m[1]));
    expect([...used].sort()).toEqual(Object.keys(TEMPLATES).sort());
    const missing: string[] = [];
    for (const [template, values] of Object.entries(TEMPLATES)) {
      expect(values.length, template).toBeGreaterThan(0);
      for (const value of values) {
        const key = template.replace(/\$\{[^}]+\}/, value);
        try {
          t(key);
        } catch {
          missing.push(key);
        }
      }
    }
    expect(missing).toEqual([]);
  });
});
