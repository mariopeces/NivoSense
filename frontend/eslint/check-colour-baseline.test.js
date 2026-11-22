import { describe, expect, it } from "vitest";
import { baselineProblems } from "./check-colour-baseline.js";

const exists = () => true;
const base = { "src/App.tsx": { "#081020": 1 } };

describe("baselineProblems", () => {
  it("accepts an unchanged or shrunk baseline", () => {
    expect(baselineProblems(base, base, exists)).toEqual([]);
    expect(baselineProblems(base, {}, exists)).toEqual([]);
  });

  it("rejects a new file, a new value and a higher count", () => {
    expect(baselineProblems(base, { "src/New.tsx": { "#fff": 1 } }, exists)).toHaveLength(1);
    expect(baselineProblems(base, { "src/App.tsx": { "#081020": 1, "#fff": 1 } }, exists)).toHaveLength(1);
    expect(baselineProblems(base, { "src/App.tsx": { "#081020": 2 } }, exists)).toHaveLength(1);
  });

  it("rejects entries for files that no longer exist, with or without a base", () => {
    expect(baselineProblems(base, base, () => false)).toHaveLength(1);
    expect(baselineProblems(null, base, () => false)).toHaveLength(1);
  });
});
