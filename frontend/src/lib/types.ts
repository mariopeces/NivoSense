export type Basin = {
  id: string;
  name: string;
  areaKm2?: number;
};

export type Route = {
  id: string;
  name: string;
  type: "ski_touring" | "snowshoe";
  lengthKm?: number;
};

export type CoverageSeriesPoint = {
  month: string; // "Jul", "Aug", ...
  observed?: number; // 0..100, undefined for future months
  forecast?: number;
  average: number;
};
