import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import {
  BookOpenText,
  Cctv,
  CloudSunRain,
  Droplets,
  Map as MapIcon,
  Mountain,
  PanelLeftClose,
  PanelLeftOpen,
  Snowflake,
  type LucideIcon,
} from "lucide-react";
import { Icon } from "../lib/icons";
import { t } from "../lib/copy";
import { BASEMAPS, type Basemap } from "../lib/basemaps";

export type Section = "nieve" | "agua" | "webcams" | "meteo" | "metodo";

export const SECTIONS: Array<{ id: Section; icon: LucideIcon }> = [
  { id: "nieve", icon: Snowflake },
  { id: "agua", icon: Droplets },
  { id: "webcams", icon: Cctv },
  { id: "meteo", icon: CloudSunRain },
  { id: "metodo", icon: BookOpenText },
];

type Props = {
  section: Section;
  onSection: (section: Section) => void;
  panelOpen: boolean;
  onTogglePanel: () => void;
  basemap: Basemap;
  onBasemap: (basemap: Basemap) => void;
  terrain: boolean;
  onToggleTerrain: () => void;
};

const STEP: Record<string, number> = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 };

/** The section a key press in the rail moves to (arrows wrap; Home and End jump), or null for other keys. */
export function sectionAfterKey(current: Section, key: string): Section | null {
  const last = SECTIONS.length - 1;
  const index = SECTIONS.findIndex((item) => item.id === current);
  if (key in STEP) return SECTIONS[(index + STEP[key] + SECTIONS.length) % SECTIONS.length].id;
  if (key === "Home") return SECTIONS[0].id;
  if (key === "End") return SECTIONS[last].id;
  return null;
}

const BUTTON =
  "relative flex h-rail-button w-rail-button flex-col items-center justify-center gap-1 rounded-md text-caption " +
  "transition-colors duration-fast ease-standard hover:bg-ink-raised hover:text-on-ink-strong " +
  "focus-visible:outline-on-ink-strong max-md:h-tabbar max-md:w-auto max-md:min-w-touch max-md:flex-1";

export default function Rail({
  section,
  onSection,
  panelOpen,
  onTogglePanel,
  basemap,
  onBasemap,
  terrain,
  onToggleTerrain,
}: Props) {
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);

  // Arrow keys move between sections (roving tab index), as the spec's keyboard section asks.
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const next = sectionAfterKey(section, event.key);
    if (!next) return;
    event.preventDefault();
    onSection(next);
    tabRefs.current[SECTIONS.findIndex((item) => item.id === next)]?.focus();
  };

  return (
    <nav
      aria-label={t("app.nombre")}
      className="absolute z-rail flex bg-ink text-on-ink md:inset-y-0 md:left-0 md:w-rail md:flex-col md:items-center md:gap-1 md:py-3 max-md:inset-x-0 max-md:bottom-0 max-md:h-tabbar max-md:px-1"
    >
      <a
        href={import.meta.env.BASE_URL}
        aria-label={t("app.nombre")}
        title={t("app.nombre")}
        className="mb-2 grid h-12 w-rail-button place-items-center border-b border-ink-line focus-visible:outline-on-ink-strong max-md:hidden"
      >
        <img
          src={`${import.meta.env.BASE_URL}logo-mark.png`}
          alt={t("app.nombre")}
          className="h-8 w-auto max-w-[44px] object-contain"
        />
      </a>

      <div
        role="tablist"
        aria-orientation="vertical"
        onKeyDown={onKeyDown}
        className="flex gap-1 md:flex-col max-md:w-full max-md:justify-around"
      >
        {SECTIONS.map((item, index) => {
          const active = item.id === section;
          return (
            <button
              key={item.id}
              ref={(node) => {
                tabRefs.current[index] = node;
              }}
              type="button"
              role="tab"
              id={`tab-${item.id}`}
              aria-selected={active}
              aria-controls="panel"
              tabIndex={active ? 0 : -1}
              title={t(`rail.tooltip_${item.id}`)}
              onClick={() => onSection(item.id)}
              className={`${BUTTON} ${active ? "bg-ink-raised text-on-ink-strong" : ""}`}
            >
              {active && (
                <span
                  aria-hidden="true"
                  className="absolute rounded-sm bg-accent md:-left-[6px] md:bottom-3 md:top-3 md:w-[3px] max-md:inset-x-4 max-md:top-0 max-md:h-[3px]"
                />
              )}
              <Icon icon={item.icon} size={20} />
              <span>{t(`rail.${item.id}`)}</span>
            </button>
          );
        })}
      </div>

      <div className="mt-auto flex flex-col gap-1 max-md:hidden">
        <BasemapButton basemap={basemap} onBasemap={onBasemap} />
        <button
          type="button"
          aria-pressed={terrain}
          title={t(terrain ? "rail.tooltip_relieve_3d_off" : "rail.tooltip_relieve_3d_on")}
          onClick={onToggleTerrain}
          className={`${BUTTON} ${terrain ? "bg-ink-raised text-on-ink-strong" : ""}`}
        >
          <Icon icon={Mountain} size={20} />
          <span>{t("rail.relieve_3d")}</span>
        </button>
        <button
          type="button"
          aria-controls="panel"
          aria-expanded={panelOpen}
          title={t(panelOpen ? "rail.tooltip_ocultar_panel" : "rail.tooltip_mostrar_panel")}
          onClick={onTogglePanel}
          className={BUTTON}
        >
          <Icon icon={panelOpen ? PanelLeftClose : PanelLeftOpen} size={20} />
          <span>{t(panelOpen ? "rail.ocultar_panel" : "rail.mostrar_panel")}</span>
        </button>
      </div>
    </nav>
  );
}

function BasemapButton({ basemap, onBasemap }: { basemap: Basemap; onBasemap: (basemap: Basemap) => void }) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    popoverRef.current?.querySelector<HTMLInputElement>("input:checked")?.focus();
    const close = (returnFocus: boolean) => {
      setOpen(false);
      if (returnFocus) buttonRef.current?.focus();
    };
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") close(true);
    };
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!popoverRef.current?.contains(target) && !buttonRef.current?.contains(target)) close(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open]);

  return (
    <div className="relative">
      <button
        ref={buttonRef}
        type="button"
        aria-expanded={open}
        aria-haspopup="dialog"
        title={t("rail.tooltip_mapa_base")}
        onClick={() => setOpen((value) => !value)}
        className={`${BUTTON} ${open ? "bg-ink-raised text-on-ink-strong" : ""}`}
      >
        <Icon icon={MapIcon} size={20} />
        <span>{t("rail.mapa_base")}</span>
      </button>
      {open && (
        <div
          ref={popoverRef}
          role="dialog"
          aria-label={t("mapa_base.titulo")}
          className="absolute bottom-0 left-[calc(100%+12px)] z-popover w-[280px] rounded-lg bg-panel p-4 text-text shadow-popover"
        >
          <fieldset className="m-0 border-0 p-0">
            <legend className="mb-3 p-0 font-semibold">{t("mapa_base.titulo")}</legend>
            {BASEMAPS.map((id) => (
              <label
                key={id}
                className="mb-1 flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 hover:bg-panel-soft"
              >
                <input
                  type="radio"
                  name="basemap"
                  value={id}
                  checked={basemap === id}
                  onChange={() => onBasemap(id)}
                  className="accent-ink"
                />
                {t(`mapa_base.${id}`)}
              </label>
            ))}
          </fieldset>
          <p className="mb-0 mt-2 text-small text-text-muted">{t("mapa_base.nota_rgb")}</p>
        </div>
      )}
    </div>
  );
}
