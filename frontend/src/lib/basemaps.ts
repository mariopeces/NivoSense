export const BASEMAPS = ["claro", "ortofoto"] as const;
export type Basemap = (typeof BASEMAPS)[number];
