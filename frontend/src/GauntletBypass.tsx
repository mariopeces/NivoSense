declare const shade: string;
export const partialHex = `#${shade}ff00`;
export function GauntletBypass() {
  return <span style={{ textDecoration: "underline wavy red", filter: "drop-shadow(0 0 2px red)" }} />;
}
