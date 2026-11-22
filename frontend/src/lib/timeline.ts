import type { CatalogIndex, CatalogStatus } from "./catalog";
import type { Status } from "../components/ui";

// Start of hydrological year 2025-26, where the published history begins (docs/plan/README.md, goal).
export const SEASON_START = "2025-10-01";

export const STATUS_OF: Record<CatalogStatus, Status> = {
  observed: "observado",
  gapfilled: "rellenado",
  modelled: "modelado",
  forecast: "prevision",
};
// Best first: a day shows the strongest evidence it has.
const RANK: Status[] = ["observado", "rellenado", "modelado", "prevision"];

export type TimelineDay = {
  date: string;
  /** Every status published for the day, best first; empty when nothing is. */
  statuses: Status[];
  best: Status;
};

export type TimelineModel = {
  days: TimelineDay[];
  todayIndex: number;
  /** Days with at least one product, ascending. */
  dataIndices: number[];
  /** Days with an observed product (a clear satellite pass), ascending. */
  observedIndices: number[];
  /** The most recent day with a product up to today, or the most recent day with any product. */
  latestIndex: number;
};

export type StripSegment = { start: number; end: number; status: Status; forecastSlot: boolean };

const DAY_MS = 86_400_000;

function toTime(iso: string) {
  return Date.parse(`${iso}T00:00:00Z`);
}

export function addDays(iso: string, days: number) {
  return new Date(toTime(iso) + days * DAY_MS).toISOString().slice(0, 10);
}

export function todayInMadrid(now = new Date()) {
  // en-CA formats as YYYY-MM-DD.
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Madrid" }).format(now);
}

/** The timeline over the whole history, or null when the catalogue lists no product at all. */
export function buildTimeline(index: CatalogIndex, today: string): TimelineModel | null {
  const byDate = new Map<string, Set<Status>>();
  for (const layer of Object.values(index.layers)) {
    for (const entry of layer.entries) {
      const statuses = byDate.get(entry.date) ?? new Set<Status>();
      statuses.add(STATUS_OF[entry.status]);
      byDate.set(entry.date, statuses);
    }
  }
  if (byDate.size === 0) return null;

  const dates = [...byDate.keys()].sort();
  const start = dates[0] < SEASON_START ? dates[0] : SEASON_START;
  const end = dates[dates.length - 1] > today ? dates[dates.length - 1] : today;
  const length = Math.round((toTime(end) - toTime(start)) / DAY_MS) + 1;

  const days: TimelineDay[] = [];
  const dataIndices: number[] = [];
  const observedIndices: number[] = [];
  for (let i = 0; i < length; i++) {
    const date = addDays(start, i);
    const present = byDate.get(date);
    const statuses = present ? RANK.filter((status) => present.has(status)) : [];
    days.push({ date, statuses, best: statuses[0] ?? "pendiente" });
    if (statuses.length) dataIndices.push(i);
    if (statuses[0] === "observado") observedIndices.push(i);
  }
  const todayIndex = days.findIndex((day) => day.date === today);
  const upToToday = dataIndices.filter((i) => i <= todayIndex);
  const latestIndex = upToToday.length ? upToToday[upToToday.length - 1] : dataIndices[dataIndices.length - 1];
  return { days, todayIndex, dataIndices, observedIndices, latestIndex };
}

/** Runs of days with the same status, split at today so the forecast slot is its own run. */
export function stripSegments(model: TimelineModel): StripSegment[] {
  const segments: StripSegment[] = [];
  model.days.forEach((day, i) => {
    const forecastSlot = i > model.todayIndex;
    const last = segments[segments.length - 1];
    if (last && last.status === day.best && last.forecastSlot === forecastSlot) {
      last.end = i + 1;
    } else {
      segments.push({ start: i, end: i + 1, status: day.best, forecastSlot });
    }
  });
  return segments;
}

export function previousIn(indices: number[], current: number): number | null {
  for (let i = indices.length - 1; i >= 0; i--) if (indices[i] < current) return indices[i];
  return null;
}

export function nextIn(indices: number[], current: number): number | null {
  for (const index of indices) if (index > current) return index;
  return null;
}

/**
 * Where a key on the timeline slider moves the cursor (docs/design/README.md, 4.2): arrows step one day,
 * Shift + arrows jump to the previous or next clear pass, Home and End go to the ends. Null when the key
 * does not move it.
 */
export function keyTarget(model: TimelineModel, current: number, key: string, shift: boolean): number | null {
  const last = model.days.length - 1;
  let target: number | null;
  switch (key) {
    case "ArrowLeft":
    case "ArrowDown":
      target = shift ? previousIn(model.observedIndices, current) : current - 1;
      break;
    case "ArrowRight":
    case "ArrowUp":
      target = shift ? nextIn(model.observedIndices, current) : current + 1;
      break;
    case "Home":
      target = 0;
      break;
    case "End":
      target = last;
      break;
    default:
      return null;
  }
  if (target === null || target < 0 || target > last || target === current) return null;
  return target;
}

/** A CSS duration in milliseconds. The production CSS minifier rewrites "800ms" as ".8s". */
export function durationMs(value: string): number {
  const match = /^\s*(\d*\.?\d+)(ms|s)\s*$/.exec(value);
  if (!match) throw new Error(`Not a CSS duration: ${value}`);
  return Number(match[1]) * (match[2] === "s" ? 1000 : 1);
}

/** The first day of every month on the track, for the month labels. */
export function monthStarts(model: TimelineModel): Array<{ index: number; date: string }> {
  return model.days.flatMap((day, index) => (day.date.endsWith("-01") ? [{ index, date: day.date }] : []));
}

export type TrackGeometry = {
  /** Width of the past part, from the first day to the end of today. */
  pastPx: number;
  /** Width of the forecast slot after today; it is drawn even when the catalogue has no forecast. */
  slotPx: number;
  /** Left edge, in px, of day position i (fractions allowed; days.length is the right end). */
  x: (i: number) => number;
  /** The day under a horizontal position in px. */
  dayAt: (px: number) => number;
};

/**
 * Pixel geometry of the track (docs/design/README.md, 4.2): the past days share the track minus the forecast
 * slot, which keeps at least minSlotPx so "Hoy" and "Previsión" stay readable, and grows with the forecast
 * days when they need more. The slot never takes more than half the track.
 */
export function trackGeometry(model: TimelineModel, widthPx: number, minSlotPx: number): TrackGeometry {
  const past = model.todayIndex + 1;
  const forecast = model.days.length - past;
  const width = Math.max(widthPx, 0);
  const slotPx = Math.min(Math.max(minSlotPx, (width * forecast) / model.days.length), width / 2);
  const pastPx = width - slotPx;
  const x = (i: number) => (i <= past ? (pastPx * i) / past : pastPx + (slotPx * (i - past)) / Math.max(forecast, 1));
  const dayAt = (px: number) => {
    if (pastPx <= 0) return 0;
    if (px < pastPx || forecast === 0) return Math.min(past - 1, Math.max(0, Math.floor((px / pastPx) * past)));
    return past + Math.min(forecast - 1, Math.floor(((px - pastPx) / slotPx) * forecast));
  };
  return { pastPx, slotPx, x, dayAt };
}

/**
 * Drops month labels that would touch their neighbour. Labels are centred on their x; the year label
 * (January) is wider than an initial and wins a collision, so the year never disappears.
 */
export function spreadLabels<T extends { x: number; wide: boolean }>(labels: T[], initialPx: number, yearPx: number, gapPx: number): T[] {
  const half = (l: T) => (l.wide ? yearPx : initialPx) / 2;
  const kept: T[] = [];
  const ordered = [...labels.filter((l) => l.wide), ...labels.filter((l) => !l.wide)];
  for (const label of ordered) {
    if (!kept.some((k) => Math.abs(k.x - label.x) < half(k) + half(label) + gapPx)) kept.push(label);
  }
  return kept.sort((a, b) => a.x - b.x);
}
