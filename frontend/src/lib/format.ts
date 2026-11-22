// Spanish formats from the copy deck: "21 feb 2026", "sábado 21 de febrero de 2026", decimal comma,
// a thin space for thousands only from 10 000.
const MONTHS_SHORT = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const WEEKDAYS_SHORT = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];

function utcDate(iso: string) {
  return new Date(`${iso.slice(0, 10)}T12:00:00Z`);
}

export function fechaCorta(iso: string) {
  const d = utcDate(iso);
  return `${d.getUTCDate()} ${MONTHS_SHORT[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

export function fechaConDia(iso: string) {
  return `${WEEKDAYS_SHORT[utcDate(iso).getUTCDay()]} ${fechaCorta(iso)}`;
}

export function mesCorto(iso: string) {
  return MONTHS_SHORT[utcDate(iso).getUTCMonth()];
}

/** One-letter month for the narrow timeline track: E F M A M J J A S O N D. */
export function mesInicial(iso: string) {
  return MONTHS_LONG[utcDate(iso).getUTCMonth()][0].toUpperCase();
}

export function mesLargo(iso: string) {
  return MONTHS_LONG[utcDate(iso).getUTCMonth()];
}

export function numero(value: number, decimals = 1) {
  const fixed = Math.abs(value).toFixed(decimals);
  const [whole, fraction] = fixed.split(".");
  const grouped = whole.length > 4 ? whole.replace(/\B(?=(\d{3})+(?!\d))/g, " ") : whole;
  return `${value < 0 ? "−" : ""}${grouped}${fraction ? `,${fraction}` : ""}`;
}

const MONTHS_LONG = [
  "enero", "febrero", "marzo", "abril", "mayo", "junio",
  "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
];
const WEEKDAYS_LONG = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];

export const WEEKDAY_INITIALS = ["L", "M", "X", "J", "V", "S", "D"];

export function fechaLarga(iso: string) {
  const d = utcDate(iso);
  return `${WEEKDAYS_LONG[d.getUTCDay()]} ${d.getUTCDate()} de ${MONTHS_LONG[d.getUTCMonth()]} de ${d.getUTCFullYear()}`;
}

export function mesAnio(iso: string) {
  const d = utcDate(iso);
  return `${MONTHS_LONG[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

export function horaMadrid(value: string) {
  return new Intl.DateTimeFormat("es-ES", {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: "Europe/Madrid",
  }).format(new Date(value));
}
