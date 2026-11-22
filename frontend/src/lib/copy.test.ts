import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { t } from "./copy";

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const file = path.join(dir, name);
    if (statSync(file).isDirectory()) return sources(file);
    return /\.tsx?$/.test(name) && !name.includes(".test.") ? [file] : [];
  });
}

describe("copy deck", () => {
  it("fills braced tokens", () => {
    expect(t("fila_capa.mostrar", { capa: "SWE" })).toBe("Mostrar SWE");
  });

  it("has every literal key the interface uses", () => {
    const root = path.resolve(__dirname, "..");
    const keys = new Set<string>();
    for (const file of sources(root)) {
      for (const match of readFileSync(file, "utf8").matchAll(/\bt\(\s*"([a-z0-9_.]+)"/g)) keys.add(match[1]);
    }
    expect(keys.size).toBeGreaterThan(50);
    for (const key of keys) expect(() => t(key), key).not.toThrow();
  });
});
