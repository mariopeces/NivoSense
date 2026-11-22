import deck from "../../../docs/design/copy.es.json";

type Deck = { [key: string]: string | Deck };

// Every UI string comes from the design spec's copy deck; braced tokens like {fecha_corta} are filled here.
export function t(key: string, vars: Record<string, string | number> = {}): string {
  let node: string | Deck | undefined = deck as Deck;
  for (const part of key.split(".")) {
    node = typeof node === "object" ? node[part] : undefined;
  }
  if (typeof node !== "string") throw new Error(`Missing copy key ${key}`);
  return node.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in vars ? String(vars[name]) : match,
  );
}
