import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";
import { t } from "./copy";
import { BASEMAPS } from "./basemaps";
import { WEATHER_VARIABLES } from "./weather";
import { SECTIONS } from "../components/Rail";
import { ROWS } from "../components/NieveSection";
import { LAYERS } from "../components/MetodoSection";
import { STATUSES } from "../components/ui";

// t() throws on a missing key and nothing catches it at render, so every key the interface can ask for must
// exist. Every argument of every t() call in src/ is read with the TypeScript parser and resolved to the keys
// it can take: string literals, both branches of a ternary, every value of a lookup table, and templates
// expanded over the values they take at render. An argument the test cannot resolve fails it.
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

type Found = { keys: string[]; templates: string[]; unresolved: string[] };

/** Every key the t() calls of one source can ask for. */
function keysInSource(fileName: string, text: string): Found {
  const source = ts.createSourceFile(fileName, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const found: Found = { keys: [], templates: [], unresolved: [] };
  // Top-level `const NAME = { ... }` tables, so `t(TABLE[x])` resolves to every value of TABLE.
  const tables = new Map<string, ts.ObjectLiteralExpression>();
  source.forEachChild(function collect(node) {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) {
      let init: ts.Expression = node.initializer;
      while (ts.isAsExpression(init) || ts.isSatisfiesExpression(init) || ts.isParenthesizedExpression(init)) {
        init = init.expression;
      }
      if (ts.isObjectLiteralExpression(init)) tables.set(node.name.text, init);
    }
    node.forEachChild(collect);
  });
  const resolve = (expr: ts.Expression) => {
    if (ts.isParenthesizedExpression(expr)) return resolve(expr.expression);
    if (ts.isStringLiteral(expr) || ts.isNoSubstitutionTemplateLiteral(expr)) return void found.keys.push(expr.text);
    if (ts.isConditionalExpression(expr)) {
      resolve(expr.whenTrue);
      return resolve(expr.whenFalse);
    }
    if (ts.isTemplateExpression(expr)) return void found.templates.push(expr.getText(source).slice(1, -1));
    if (ts.isElementAccessExpression(expr) && ts.isIdentifier(expr.expression) && tables.has(expr.expression.text)) {
      for (const prop of tables.get(expr.expression.text)!.properties) {
        if (ts.isPropertyAssignment(prop)) resolve(prop.initializer);
        else found.unresolved.push(`${fileName}: ${prop.getText(source)}`);
      }
      return;
    }
    found.unresolved.push(`${fileName}: t(${expr.getText(source)})`);
  };
  source.forEachChild(function visit(node) {
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === "t") {
      if (node.arguments.length) resolve(node.arguments[0]);
    }
    node.forEachChild(visit);
  });
  return found;
}

function missingKeys(keys: Iterable<string>) {
  return [...keys].filter((key) => {
    try {
      t(key);
      return false;
    } catch {
      return true;
    }
  });
}

const root = path.resolve(__dirname, "..");
const all = sources(root).map((file) => keysInSource(path.relative(root, file), readFileSync(file, "utf8")));
const keys = new Set(all.flatMap((f) => f.keys));
const templates = new Set(all.flatMap((f) => f.templates));

describe("copy deck", () => {
  it("fills braced tokens", () => {
    expect(t("fila_capa.mostrar", { capa: "SWE" })).toBe("Mostrar SWE");
  });

  it("resolves the argument of every t() call in the interface", () => {
    expect(all.flatMap((f) => f.unresolved)).toEqual([]);
    expect(keys.size).toBeGreaterThan(80);
  });

  it("has every literal, ternary and lookup-table key, whatever its section", () => {
    expect(missingKeys(keys)).toEqual([]);
  });

  it("knows every template key the code composes, and every expansion exists", () => {
    expect([...templates].sort()).toEqual(Object.keys(TEMPLATES).sort());
    const expanded: string[] = [];
    for (const [template, values] of Object.entries(TEMPLATES)) {
      expect(values.length, template).toBeGreaterThan(0);
      for (const value of values) expanded.push(template.replace(/\$\{[^}]+\}/, value));
    }
    expect(missingKeys(expanded)).toEqual([]);
  });

  it("catches a key in a section the deck does not have, in a literal, a ternary or a table", () => {
    const typo = keysInSource(
      "typo.tsx",
      `const TITLE = { a: "leyendas.experimental" } as const;
       t("leyendas.experimental"); t(on ? "Leyenda.x" : "leyenda.experimental"); t(TITLE[k]);`,
    );
    expect(typo.unresolved).toEqual([]);
    expect(missingKeys(typo.keys)).toEqual(["leyendas.experimental", "Leyenda.x", "leyendas.experimental"]);
  });
});
