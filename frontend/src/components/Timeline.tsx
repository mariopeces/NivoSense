import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { ArrowRightToLine, Calendar, ChevronLeft, ChevronRight, Pause, Play } from "lucide-react";
import { Icon } from "../lib/icons";
import { t } from "../lib/copy";
import { token } from "../lib/tokens";
import { WEEKDAY_INITIALS, fechaConDia, fechaLarga, mesAnio, mesCorto } from "../lib/format";
import type { CatalogState } from "../lib/catalog";
import {
  durationMs,
  keyTarget,
  monthStarts,
  nextIn,
  previousIn,
  stripSegments,
  type TimelineModel,
} from "../lib/timeline";
import { StatusBadge, StatusGlyph, type Status } from "./ui";

type Props = {
  catalog: CatalogState;
  model: TimelineModel | null;
  selectedDate: string | null;
  onChange: (date: string) => void;
  onRetry: () => void;
  hidden?: boolean;
  mobile: boolean;
};

const ICON_BUTTON =
  "grid h-8 w-8 place-items-center rounded-md border border-line bg-panel text-text transition-colors duration-fast " +
  "hover:bg-panel-soft disabled:cursor-not-allowed disabled:text-line-strong disabled:hover:bg-panel max-md:h-touch max-md:w-touch";
const TEXT_BUTTON =
  "inline-flex h-8 items-center gap-2 rounded-md border border-line bg-panel px-3 text-small font-medium " +
  "hover:bg-panel-soft disabled:cursor-not-allowed disabled:text-text-muted disabled:hover:bg-panel max-md:h-touch";
const SHELL = "shell-timeline absolute z-timeline mx-auto max-w-[1000px] rounded-lg bg-panel px-3 py-2 shadow-float";

// Status as shape: solid tick for a clear pass; outline, half-filled, dashed and dotted day segments.
const SEGMENT: Record<Status, string> = {
  observado: "border-[1.5px] border-solid border-status-observed bg-status-observed",
  rellenado: "border-[1.5px] border-solid border-status-gapfilled bg-panel",
  modelado:
    "border-[1.5px] border-solid border-status-modelled bg-gradient-to-t from-status-modelled from-50% to-panel to-50%",
  prevision: "border-[1.5px] border-dashed border-status-forecast bg-panel",
  pendiente: "border border-dotted border-status-pending bg-panel",
};
const LEGEND: Status[] = ["observado", "rellenado", "modelado", "prevision", "pendiente"];

function statusList(statuses: Status[]) {
  return (statuses.length ? statuses : (["pendiente"] as Status[])).map((s) => t(`estado.${s}`)).join(", ");
}

// The map date over the whole history in catalog/index.json: a track with a tick per clear pass, a daily
// strip with the best status of each day, and the forecast slot after today.
export default function Timeline({ catalog, model, selectedDate, onChange, onRetry, hidden = false, mobile }: Props) {
  const [playing, setPlaying] = useState(false);
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [hover, setHover] = useState<number | null>(null);
  const calendarButton = useRef<HTMLButtonElement | null>(null);
  const trackRef = useRef<HTMLDivElement | null>(null);
  const dragging = useRef(false);

  const index = model && selectedDate ? model.days.findIndex((day) => day.date === selectedDate) : -1;

  useEffect(() => {
    if (!playing || !model) return;
    // Play steps through the days that have a product; empty days would show nothing new.
    const next = nextIn(model.dataIndices, index);
    if (next === null) {
      setPlaying(false);
      return;
    }
    const timer = window.setTimeout(
      () => onChange(model.days[next].date),
      durationMs(token("motion-duration-play-frame")),
    );
    return () => window.clearTimeout(timer);
  }, [playing, model, index, onChange]);

  const segments = useMemo(() => (model ? stripSegments(model) : []), [model]);
  const months = useMemo(() => (model ? monthStarts(model) : []), [model]);

  // No timeline until the catalogue answers: the dates are unknown until then.
  if (hidden || catalog.kind === "loading") return null;

  if (catalog.kind === "error") {
    return (
      <div role="alert" className={`${SHELL} flex flex-wrap items-center gap-3`}>
        <div className="py-1">
          <p className="m-0 font-semibold">{t("error.catalogo_titulo")}</p>
          <p className="m-0 text-small text-text-muted">{t("error.catalogo_detalle")}</p>
        </div>
        <button type="button" className={`${TEXT_BUTTON} ml-auto`} onClick={onRetry}>
          {t("error.reintentar")}
        </button>
      </div>
    );
  }

  if (!model || index < 0) {
    return (
      <div role="status" aria-label={t("linea_tiempo.etiqueta")} className={SHELL}>
        <div className="py-1">
          <p className="m-0 font-semibold">{t("linea_tiempo.sin_datos")}</p>
          <p className="m-0 text-small text-text-muted">{t("linea_tiempo.sin_datos_detalle")}</p>
        </div>
      </div>
    );
  }

  const span = model.days.length;
  const pct = (i: number) => (100 * i) / span;
  const day = model.days[index];
  const previous = previousIn(model.dataIndices, index);
  const next = nextIn(model.dataIndices, index);
  const latest = model.days[model.latestIndex];
  const lastForecast = model.days.length - 1 > model.todayIndex;

  const select = (i: number) => onChange(model.days[i].date);
  const dayAt = (clientX: number) => {
    const rect = trackRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0) return index;
    const x = Math.min(Math.max(clientX - rect.left, 0), rect.width - 1);
    return Math.floor((x / rect.width) * span);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === " ") {
      event.preventDefault();
      setPlaying((value) => !value);
      return;
    }
    const target = keyTarget(model, index, event.key, event.shiftKey);
    if (target === null) return;
    event.preventDefault();
    setPlaying(false);
    select(target);
  };
  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    dragging.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    setPlaying(false);
    select(dayAt(event.clientX));
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const at = dayAt(event.clientX);
    if (event.pointerType === "mouse") setHover(at);
    if (dragging.current && at !== index) select(at);
  };
  const onPointerUp = () => {
    dragging.current = false;
  };

  const tooltipIndex = hover;
  const tooltipAlign =
    tooltipIndex === null ? "" : pct(tooltipIndex) < 15 ? "translate-x-0" : pct(tooltipIndex) > 85 ? "-translate-x-full" : "-translate-x-1/2";

  return (
    <div
      role="group"
      aria-label={t("linea_tiempo.etiqueta")}
      className={`${SHELL} grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1 max-md:grid-cols-[minmax(0,1fr)_auto]`}
    >
      <div className="flex min-w-[150px] flex-col md:row-span-2">
        <span className="text-small text-text-muted">{t("linea_tiempo.etiqueta")}</span>
        <time dateTime={day.date} title={fechaLarga(day.date)} className="tnum font-semibold">
          {fechaConDia(day.date)}
        </time>
        <div className="mt-1 flex items-center gap-1">
          <button
            type="button"
            className={ICON_BUTTON}
            disabled={previous === null}
            onClick={() => previous !== null && select(previous)}
            aria-label={t("linea_tiempo.anterior")}
            title={t("linea_tiempo.anterior")}
          >
            <Icon icon={ChevronLeft} />
          </button>
          <button
            type="button"
            className={ICON_BUTTON}
            disabled={!playing && next === null}
            onClick={() => setPlaying((value) => !value)}
            aria-label={t(playing ? "linea_tiempo.pausar" : "linea_tiempo.reproducir")}
            title={t(playing ? "linea_tiempo.pausar" : "linea_tiempo.reproducir")}
          >
            <Icon icon={playing ? Pause : Play} />
          </button>
          <button
            type="button"
            className={ICON_BUTTON}
            disabled={next === null}
            onClick={() => next !== null && select(next)}
            aria-label={t("linea_tiempo.siguiente")}
            title={t("linea_tiempo.siguiente")}
          >
            <Icon icon={ChevronRight} />
          </button>
          <span className="ml-1">
            <StatusBadge status={day.best} />
          </span>
        </div>
      </div>

      <div
        ref={trackRef}
        role="slider"
        tabIndex={0}
        aria-label={t("linea_tiempo.etiqueta")}
        aria-valuemin={0}
        aria-valuemax={span - 1}
        aria-valuenow={index}
        aria-valuetext={`${fechaConDia(day.date)}: ${statusList(day.statuses)}`}
        aria-keyshortcuts="ArrowLeft ArrowRight Shift+ArrowLeft Shift+ArrowRight Home End Space"
        title={t("linea_tiempo.teclado")}
        onKeyDown={onKeyDown}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onPointerLeave={() => setHover(null)}
        className="relative h-[52px] cursor-pointer touch-none select-none rounded-sm max-md:col-span-2 max-md:row-start-2"
      >
        <div className="absolute inset-x-0 top-1 h-[14px]" aria-hidden="true">
          {model.observedIndices.map((i) => (
            <span
              key={i}
              className="absolute top-0 h-[14px] w-px rounded-[1px] bg-status-observed"
              style={{ left: `${pct(i)}%` }}
            />
          ))}
        </div>
        <div className="absolute inset-x-0 top-[21px] h-[10px]" aria-hidden="true">
          {segments.map((segment) => (
            <span
              key={segment.start}
              className={`absolute inset-y-0 box-border rounded-sm ${SEGMENT[segment.status]} ${
                segment.forecastSlot && segment.status === "pendiente" ? "bg-panel-soft" : ""
              }`}
              style={{ left: `${pct(segment.start)}%`, width: `${pct(segment.end - segment.start)}%` }}
            />
          ))}
        </div>
        <div className="absolute inset-x-0 top-[34px] h-4" aria-hidden="true">
          {months
            .filter(({ date }) => !mobile || ["01", "04", "07", "10"].includes(date.slice(5, 7)))
            // A label near the right end would run into the forecast slot label.
            .filter(({ index: i }) => !lastForecast || pct(i) < (mobile ? 80 : 88))
            .map(({ index: i, date }) => {
              const january = date.slice(5, 7) === "01";
              return (
                <span
                  key={date}
                  className={`absolute -translate-x-1/2 whitespace-nowrap text-caption ${
                    january ? "font-semibold text-text" : "text-text-muted"
                  }`}
                  style={{ left: `${pct(i)}%` }}
                >
                  {january ? date.slice(0, 4) : mesCorto(date)}
                </span>
              );
            })}
          {lastForecast && (
            <span
              className="absolute right-0 whitespace-nowrap text-caption text-status-forecast"
              title={t("linea_tiempo.tooltip_prevision_slot")}
            >
              {t("linea_tiempo.prevision_slot")}
            </span>
          )}
        </div>
        <span
          aria-hidden="true"
          title={t("linea_tiempo.hoy")}
          className="absolute bottom-4 top-0 w-0 border-l border-dashed border-text-muted"
          style={{ left: `${pct(model.todayIndex + 1)}%` }}
        />
        <span
          aria-hidden="true"
          className="pointer-events-none absolute bottom-4 top-[-4px] w-[2px] -translate-x-1/2 bg-accent"
          style={{ left: `${pct(index + 0.5)}%` }}
        >
          <span className="absolute left-1/2 top-[-4px] h-[10px] w-[10px] -translate-x-1/2 rounded-full border-2 border-panel bg-accent" />
        </span>
        {tooltipIndex !== null && (
          <span
            aria-hidden="true"
            className={`pointer-events-none absolute bottom-[calc(100%+8px)] whitespace-nowrap rounded-md bg-ink px-3 py-2 text-caption text-on-ink-strong shadow-popover ${tooltipAlign}`}
            style={{ left: `${pct(tooltipIndex + 0.5)}%` }}
          >
            {t("linea_tiempo.tick_tooltip", {
              fecha_larga: fechaLarga(model.days[tooltipIndex].date),
              estados: statusList(model.days[tooltipIndex].statuses),
            })}
          </span>
        )}
      </div>

      <div className="relative flex items-center gap-1 justify-self-end max-md:col-start-2 max-md:row-start-1">
        <button
          type="button"
          disabled={latest.date === day.date}
          onClick={() => {
            setPlaying(false);
            onChange(latest.date);
          }}
          title={t("linea_tiempo.tooltip_ultima")}
          className={TEXT_BUTTON}
        >
          <Icon icon={ArrowRightToLine} />
          {t("linea_tiempo.ultima")}
        </button>
        <button
          ref={calendarButton}
          type="button"
          className={ICON_BUTTON}
          aria-expanded={calendarOpen}
          aria-haspopup="dialog"
          onClick={() => setCalendarOpen((value) => !value)}
          aria-label={t("linea_tiempo.calendario")}
          title={t("linea_tiempo.calendario")}
        >
          <Icon icon={Calendar} />
        </button>
        {calendarOpen && (
          <DayCalendar
            model={model}
            selectedDate={day.date}
            onSelect={(date) => {
              setPlaying(false);
              onChange(date);
              setCalendarOpen(false);
              calendarButton.current?.focus();
            }}
            onClose={() => {
              setCalendarOpen(false);
              calendarButton.current?.focus();
            }}
          />
        )}
      </div>

      {!mobile && (
        <ul className="col-span-2 col-start-2 m-0 flex list-none flex-wrap gap-4 p-0">
          {LEGEND.map((status) => (
            <li key={status} title={t(`estado.tooltip_${status}`)} className="inline-flex items-center gap-1 text-caption text-text-muted">
              <StatusGlyph status={status} />
              {t(`linea_tiempo.leyenda_${status}`)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// Secondary way to pick a date: a month grid where only days with a product can be chosen.
function DayCalendar({
  model,
  selectedDate,
  onSelect,
  onClose,
}: {
  model: TimelineModel;
  selectedDate: string;
  onSelect: (date: string) => void;
  onClose: () => void;
}) {
  const [visibleMonth, setVisibleMonth] = useState(() => selectedDate.slice(0, 7));
  const ref = useRef<HTMLDivElement | null>(null);
  const byDate = useMemo(() => new Map(model.days.map((day) => [day.date, day])), [model]);
  const firstMonth = model.days[0].date.slice(0, 7);
  const lastMonth = model.days[model.days.length - 1].date.slice(0, 7);
  const days = calendarDays(visibleMonth);

  useEffect(() => {
    ref.current?.querySelector<HTMLButtonElement>("[aria-pressed=true]")?.focus();
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      ref={ref}
      role="dialog"
      aria-label={t("linea_tiempo.calendario")}
      className="absolute bottom-[calc(100%+12px)] right-0 z-popover w-[300px] rounded-lg bg-panel p-3 shadow-popover"
    >
      <div className="mb-2 flex items-center justify-between">
        <button
          type="button"
          onClick={() => setVisibleMonth(addMonths(visibleMonth, -1))}
          disabled={visibleMonth <= firstMonth}
          className={ICON_BUTTON}
          aria-label={t("calendario.mes_anterior")}
          title={t("calendario.mes_anterior")}
        >
          <Icon icon={ChevronLeft} />
        </button>
        <span className="font-semibold">{mesAnio(`${visibleMonth}-01`)}</span>
        <button
          type="button"
          onClick={() => setVisibleMonth(addMonths(visibleMonth, 1))}
          disabled={visibleMonth >= lastMonth}
          className={ICON_BUTTON}
          aria-label={t("calendario.mes_siguiente")}
          title={t("calendario.mes_siguiente")}
        >
          <Icon icon={ChevronRight} />
        </button>
      </div>
      <div className="grid grid-cols-7 gap-1 text-center text-caption text-text-muted" aria-hidden="true">
        {WEEKDAY_INITIALS.map((initial) => (
          <span key={initial} className="py-1">
            {initial}
          </span>
        ))}
      </div>
      <div className="mt-1 grid grid-cols-7 gap-1">
        {days.map((date) => {
          const status = byDate.get(date)?.best ?? "pendiente";
          const available = status !== "pendiente";
          const active = date === selectedDate;
          const inMonth = date.startsWith(visibleMonth);
          return (
            <button
              key={date}
              type="button"
              onClick={() => available && onSelect(date)}
              disabled={!available}
              aria-pressed={active}
              aria-label={`${fechaLarga(date)}: ${t(`estado.${status}`)}`}
              className={`tnum relative flex h-8 items-center justify-center rounded-md text-small ${
                active
                  ? "bg-ink text-on-ink-strong"
                  : available
                    ? `border border-line-strong font-medium hover:bg-panel-soft ${status === "prevision" ? "border-dashed" : ""}`
                    : inMonth
                      ? "text-text-muted"
                      : "text-line-strong"
              }`}
            >
              {Number(date.slice(8, 10))}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function addMonths(month: string, months: number) {
  const [year, m] = month.split("-").map(Number);
  const date = new Date(Date.UTC(year, m - 1 + months, 1));
  return date.toISOString().slice(0, 7);
}

// Six Monday-first weeks covering the month, as ISO dates.
function calendarDays(month: string) {
  const start = new Date(`${month}-01T00:00:00Z`);
  const weekday = (start.getUTCDay() + 6) % 7;
  return Array.from({ length: 42 }, (_, i) =>
    new Date(start.getTime() + (i - weekday) * 86_400_000).toISOString().slice(0, 10),
  );
}
