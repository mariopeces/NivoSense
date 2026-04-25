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
  date: string;
  label: string;
  observed: number | null;
  valid_pixels?: number;
  snow_pixels?: number;
};
