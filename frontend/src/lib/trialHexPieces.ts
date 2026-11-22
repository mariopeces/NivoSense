const H = "ff0000";
const x = "ff";
const suffix = "";
export const a = `#${H}`;
export const b = `#${`ff0000`}`;
export const c = `#${"ff0000"}${suffix}`;
export const d = `#${x}ff0000`;
export const e = `\x23${x}ff00`;
