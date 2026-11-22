import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowRightToLine, Calendar, ChevronLeft, ChevronRight } from "lucide-react";
import { Icon } from "../lib/icons";
import { t } from "../lib/copy";
import { WEEKDAY_INITIALS, fechaConDia, fechaLarga, mesAnio } from "../lib/format";
import { StatusBadge } from "./ui";

export type Scene = { date: string; isPrediction: boolean };

type Props = {
  scenes: Scene[];
  loading: boolean;
  selectedDate: string | null;
  onChange: (date: string | null) => void;
  hidden?: boolean;
};

const ICON_BUTTON =
  "grid h-8 w-8 place-items-center rounded-md border border-line bg-panel text-text transition-colors duration-fast " +
  "hover:bg-panel-soft disabled:cursor-not-allowed disabled:text-line-strong disabled:hover:bg-panel max-md:h-touch max-md:w-touch";

// The map date, chosen only among dates that have a scene (observation or prediction). The full timeline
// with per-status ticks replaces this bar once the catalogue exists.
export default function DateBar({ scenes, loading, selectedDate, onChange, hidden = false }: Props) {
  const [calendarOpen, setCalendarOpen] = useState(false);
  const calendarButton = useRef<HTMLButtonElement | null>(null);

  // No bar until the scene lists answer: the dates are unknown until then.
  if (loading || hidden) return null;

  const index = scenes.findIndex((scene) => scene.date === selectedDate);
  const selected = index >= 0 ? scenes[index] : null;
  const latest = scenes.length ? scenes[scenes.length - 1] : null;

  return (
    <div
      role="group"
      aria-label={t("linea_tiempo.etiqueta")}
      className="shell-datebar absolute z-timeline mx-auto flex max-w-[1000px] flex-wrap items-center gap-3 rounded-lg bg-panel px-3 py-2 shadow-float"
    >
      {!selected ? (
        <div className="py-1">
          <p className="m-0 font-semibold">{t("linea_tiempo.sin_datos")}</p>
          <p className="m-0 text-small text-text-muted">{t("linea_tiempo.sin_datos_detalle")}</p>
        </div>
      ) : (
        <>
          <div className="flex min-w-[150px] flex-col">
            <span className="text-small text-text-muted">{t("linea_tiempo.etiqueta")}</span>
            <time dateTime={selected.date} title={fechaLarga(selected.date)} className="tnum font-semibold">
              {fechaConDia(selected.date)}
            </time>
          </div>
          <div className="flex gap-1">
            <button
              type="button"
              className={ICON_BUTTON}
              disabled={index <= 0}
              onClick={() => onChange(scenes[index - 1]?.date ?? null)}
              aria-label={t("linea_tiempo.anterior")}
              title={t("linea_tiempo.anterior")}
            >
              <Icon icon={ChevronLeft} />
            </button>
            <button
              type="button"
              className={ICON_BUTTON}
              disabled={index >= scenes.length - 1}
              onClick={() => onChange(scenes[index + 1]?.date ?? null)}
              aria-label={t("linea_tiempo.siguiente")}
              title={t("linea_tiempo.siguiente")}
            >
              <Icon icon={ChevronRight} />
            </button>
          </div>
          <StatusBadge status={selected.isPrediction ? "prevision" : "observado"} />
          <div className="relative ml-auto flex gap-1">
            <button
              type="button"
              disabled={!latest || latest.date === selected.date}
              onClick={() => latest && onChange(latest.date)}
              title={t("linea_tiempo.tooltip_ultima")}
              className="inline-flex h-8 items-center gap-2 rounded-md border border-line bg-panel px-3 text-small font-medium hover:bg-panel-soft disabled:cursor-not-allowed disabled:text-text-muted disabled:hover:bg-panel max-md:h-touch"
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
              <SceneCalendar
                scenes={scenes}
                selectedDate={selected.date}
                onSelect={(date) => {
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
        </>
      )}
    </div>
  );
}

function SceneCalendar({
  scenes,
  selectedDate,
  onSelect,
  onClose,
}: {
  scenes: Scene[];
  selectedDate: string;
  onSelect: (date: string) => void;
  onClose: () => void;
}) {
  const [visibleMonth, setVisibleMonth] = useState(() => monthStart(parseDate(selectedDate)));
  const ref = useRef<HTMLDivElement | null>(null);
  const byDate = useMemo(() => new Map(scenes.map((scene) => [scene.date, scene])), [scenes]);
  const days = calendarDays(visibleMonth);

  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  // Mount only: a parent re-render while the calendar is open must not pull focus back to the selected day.
  useEffect(() => {
    ref.current?.querySelector<HTMLButtonElement>("[aria-pressed=true]")?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCloseRef.current();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

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
          className={ICON_BUTTON}
          aria-label={t("calendario.mes_anterior")}
          title={t("calendario.mes_anterior")}
        >
          <Icon icon={ChevronLeft} />
        </button>
        <span className="font-semibold">{mesAnio(isoDate(visibleMonth))}</span>
        <button
          type="button"
          onClick={() => setVisibleMonth(addMonths(visibleMonth, 1))}
          className={ICON_BUTTON}
          aria-label={t("calendario.mes_siguiente")}
          title={t("calendario.mes_siguiente")}
        >
          <Icon icon={ChevronRight} />
        </button>
      </div>
      <div className="grid grid-cols-7 gap-1 text-center text-caption text-text-muted" aria-hidden="true">
        {WEEKDAY_INITIALS.map((day) => (
          <span key={day} className="py-1">
            {day}
          </span>
        ))}
      </div>
      <div className="mt-1 grid grid-cols-7 gap-1">
        {days.map((day) => {
          const key = isoDate(day);
          const scene = byDate.get(key);
          const active = key === selectedDate;
          const inMonth = day.getUTCMonth() === visibleMonth.getUTCMonth();
          return (
            <button
              key={key}
              type="button"
              onClick={() => scene && onSelect(key)}
              disabled={!scene}
              aria-pressed={active}
              aria-label={fechaLarga(key)}
              className={`tnum relative flex h-8 items-center justify-center rounded-md text-small ${
                active
                  ? "bg-ink text-on-ink-strong"
                  : scene
                    ? "border border-line-strong font-medium hover:bg-panel-soft"
                    : inMonth
                      ? "text-text-muted"
                      : "text-line-strong"
              } ${scene?.isPrediction && !active ? "border-dashed" : ""}`}
            >
              {day.getUTCDate()}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function parseDate(value: string) {
  return new Date(`${value}T00:00:00Z`);
}

function isoDate(value: Date) {
  return value.toISOString().slice(0, 10);
}

function monthStart(value: Date) {
  return new Date(Date.UTC(value.getUTCFullYear(), value.getUTCMonth(), 1));
}

function addMonths(value: Date, months: number) {
  return new Date(Date.UTC(value.getUTCFullYear(), value.getUTCMonth() + months, 1));
}

function calendarDays(month: Date) {
  const start = monthStart(month);
  const weekday = (start.getUTCDay() + 6) % 7;
  const first = new Date(start);
  first.setUTCDate(start.getUTCDate() - weekday);
  return Array.from({ length: 42 }, (_, index) => {
    const day = new Date(first);
    day.setUTCDate(first.getUTCDate() + index);
    return day;
  });
}
