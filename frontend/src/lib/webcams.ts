import { t } from "./copy";
import { fechaCorta, horaMadrid } from "./format";
import type { Webcam } from "./types";

export type MappedWebcam = Webcam & { latitude: number; longitude: number };

export type WebcamGroup = {
  id: string;
  longitude: number;
  latitude: number;
  cams: MappedWebcam[];
};

/** Cameras closer than this share one map point: the five feratel cameras of a station sit on one pole. */
export const GROUP_RADIUS_M = 30;
/** A still older than this is shown as "Imagen antigua" (the copy deck's rule, webcam.imagen_antigua). */
export const STALE_HOURS = 2;

// DGT names cameras "A-395 · PK 12.6" and places them in "GRANADA": shown with the copy deck's decimal
// comma ("PK 12,6") and the place in title case, and sorted along the road.
const ROAD_POINT = /PK (\d+(?:\.\d+)?)/;

export function cameraName(name: string) {
  return name.replace(ROAD_POINT, (_, km: string) => `PK ${km.replace(".", ",")}`);
}

export function placeName(place: string) {
  if (place !== place.toUpperCase()) return place;
  return place.toLowerCase().replace(/(^|[\s-])(\p{L})/gu, (_, prefix: string, ch: string) => prefix + ch.toUpperCase());
}

export function byRoadPoint(a: Webcam, b: Webcam) {
  const road = (cam: Webcam) => cam.name.replace(ROAD_POINT, "").trim();
  const km = (cam: Webcam) => Number(ROAD_POINT.exec(cam.name)?.[1] ?? Number.POSITIVE_INFINITY);
  return road(a).localeCompare(road(b), "es") || km(a) - km(b) || a.name.localeCompare(b.name, "es");
}

// The ingest stores the checked stills under the site; any other path is refused.
export function stillUrl(value: string | null) {
  if (!value || !/^data\/webcam-stills\/[\w.-]+\/[\w.-]+\.jpg$/.test(value)) return null;
  return `${import.meta.env.BASE_URL}${value}`;
}

export function cameraImage(cam: Webcam) {
  return cam.status === "live" ? stillUrl(cam.large_url ?? cam.thumbnail_url) : null;
}

export function isLive(cam: Webcam) {
  return cameraImage(cam) !== null;
}

export function isMapped(cam: Webcam): cam is MappedWebcam {
  return typeof cam.latitude === "number" && typeof cam.longitude === "number";
}

function distanceM(a: MappedWebcam, b: MappedWebcam) {
  const dLat = (b.latitude - a.latitude) * 111_320;
  const dLon = (b.longitude - a.longitude) * 111_320 * Math.cos(((a.latitude + b.latitude) / 2) * (Math.PI / 180));
  return Math.hypot(dLat, dLon);
}

/** Screen distance under which two markers would overlap and so share one. */
export const GROUP_RADIUS_PX = 26;

/** Grouping radius at a zoom: 30 m, or what 26 px cover on the ground when that is more (MapLibre's 512 px tiles). */
export function groupRadiusM(zoom: number, latitude: number) {
  const metersPerPx = (78_271.517 * Math.cos((latitude * Math.PI) / 180)) / 2 ** zoom;
  return Math.max(GROUP_RADIUS_M, GROUP_RADIUS_PX * metersPerPx);
}

/** Cameras with a position, grouped by place: a camera joins the first group whose anchor is within the radius. */
export function groupWebcams(cams: Webcam[], radiusM = GROUP_RADIUS_M): WebcamGroup[] {
  const groups: WebcamGroup[] = [];
  for (const cam of cams.filter(isMapped).sort(byRoadPoint)) {
    const group = groups.find((g) => distanceM(g.cams[0], cam) <= radiusM);
    if (group) group.cams.push(cam);
    else groups.push({ id: cam.id, longitude: cam.longitude, latitude: cam.latitude, cams: [cam] });
  }
  return groups;
}

/**
 * Screen offsets (px, y down) that spread n sub-points evenly on a circle around the origin, the first pointing
 * up. The radius grows with n so neighbours keep `spacing` px between centres, never below `minRadius`.
 */
export function fanOffsets(n: number, spacing = 44, minRadius = 56) {
  const radius = Math.max(minRadius, Math.ceil((n * spacing) / (2 * Math.PI)));
  return Array.from({ length: n }, (_, i) => {
    const angle = -Math.PI / 2 + (2 * Math.PI * i) / n;
    return { dx: Math.round(radius * Math.cos(angle)), dy: Math.round(radius * Math.sin(angle)), radius };
  });
}

/** Madrid calendar date of an instant, as the capture line shows it next to the Madrid hour. */
function fechaMadrid(value: string) {
  const day = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Madrid" }).format(new Date(value));
  return fechaCorta(day);
}

export function captureTime(iso: string) {
  return t("webcam.capturada", { fecha_corta: fechaMadrid(iso), hora: horaMadrid(iso) });
}

export function ageMinutes(iso: string, now = Date.now()) {
  return Math.max(0, Math.floor((now - new Date(iso).getTime()) / 60_000));
}

/** "hace 4 min", "hace 3 h", "hace 2 días"; past a week, the short date. */
export function captureAge(iso: string, now = Date.now()) {
  const min = ageMinutes(iso, now);
  if (min < 1) return t("webcam.edad_ahora");
  if (min < 60) return t("webcam.edad_min", { n: min });
  const hours = Math.floor(min / 60);
  if (hours < 24) return t("webcam.edad_h", { n: hours });
  const days = Math.floor(hours / 24);
  if (days === 1) return t("webcam.edad_dia");
  if (days <= 7) return t("webcam.edad_dias", { n: days });
  return fechaMadrid(iso);
}
