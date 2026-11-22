import { existsSync, readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

// The colour baseline may only shrink: compared with the PR base it cannot gain a file, a value or a count,
// and every file it names must exist (a deleted or renamed file's entries would otherwise linger).
export function baselineProblems(base, head, fileExists) {
  const problems = [];
  for (const [file, values] of Object.entries(head)) {
    if (!fileExists(file)) problems.push(`${file}: listed in the baseline but the file does not exist`);
    if (!base) continue;
    for (const [value, count] of Object.entries(values)) {
      const allowed = base[file]?.[value] ?? 0;
      if (count > allowed) problems.push(`${file}: ${value} grew from ${allowed} to ${count}`);
    }
  }
  return problems;
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [basePath] = process.argv.slice(2);
  const head = JSON.parse(readFileSync("colour-baseline.json", "utf8"));
  const base = basePath ? JSON.parse(readFileSync(basePath, "utf8")) : null;
  const problems = baselineProblems(base, head, existsSync);
  for (const problem of problems) console.error(`::error file=frontend/colour-baseline.json::${problem}`);
  if (!base) console.log("No baseline on the base branch: checked file existence only.");
  process.exitCode = problems.length ? 1 : 0;
}
