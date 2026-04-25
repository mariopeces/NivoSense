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

export type River = {
  id: string;
  name: string;
  basin_cod_uni: number;
  station_id: string;
  station_name: string;
  source: string;
  variable: string;
  unit: string;
};

export type FlowPoint = {
  date: string;
  label: string;
  value: number | null;
};

export type FlowSeries = {
  river_id: string;
  river_name: string;
  station_id: string;
  station_name: string;
  variable: string;
  unit: string;
  source: string;
  first_date: string | null;
  last_date: string | null;
  points: FlowPoint[];
};
