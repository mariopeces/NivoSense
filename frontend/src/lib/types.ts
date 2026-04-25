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
  hydro_day: number;
  observed: number | null;
  total_pixels?: number;
  valid_pixels?: number;
  masked_pixels?: number;
  data_coverage_pct?: number | null;
  snow_pixels?: number;
};

export type AverageSeriesPoint = {
  label: string;
  hydro_day: number;
  average: number | null;
  sample_count?: number;
  data_coverage_pct?: number | null;
};

export type BasinSeries = {
  basin_id: string;
  basin_name: string;
  hydrological_year: string;
  year: number;
  points: CoverageSeriesPoint[];
  average_points: AverageSeriesPoint[];
};

export type ObservationScene = {
  date: string;
  path: string;
  url: string;
  tile_url: string;
  size: number;
};
