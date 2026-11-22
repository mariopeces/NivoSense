export const TOKENS_JSON: string;
export const TOKENS_CSS: string;
export function flattenTokens(tokens: unknown): Array<[string, string]>;
export function renderTokensCss(tokens: unknown): string;
