import type { ReactNode } from "react";
import { t } from "../lib/copy";
import type { Section } from "./Rail";

export type SheetHeight = "peek" | "half" | "full";

const NEXT_SHEET: Record<SheetHeight, SheetHeight> = { peek: "half", half: "full", full: "peek" };

type Props = {
  section: Section;
  open: boolean;
  sheet: SheetHeight;
  onSheet: (sheet: SheetHeight) => void;
  children: ReactNode;
};

// Desktop: the 320 px panel next to the rail, sliding out when collapsed. Below 768 px: a bottom sheet
// above the tab bar with three heights (peek, half, full), sized by --sheet-height on the app root.
export default function Panel({ section, open, sheet, onSheet, children }: Props) {
  return (
    <section
      id="panel"
      role="tabpanel"
      aria-labelledby={`tab-${section}`}
      className={`shell-panel z-panel flex flex-col bg-panel shadow-panel ${open ? "" : "is-collapsed"}`}
    >
      <button
        type="button"
        onClick={() => onSheet(NEXT_SHEET[sheet])}
        aria-label={t("movil.asa")}
        title={t("movil.asa")}
        className="mx-auto mt-2 hidden h-6 w-16 place-items-center rounded-md max-md:grid"
      >
        <span aria-hidden="true" className="h-1 w-10 rounded-full bg-line-strong" />
      </button>
      <header className="border-b border-line px-5 pb-4 pt-5 max-md:px-4 max-md:pb-3 max-md:pt-1">
        <p className="m-0 text-eyebrow text-text-muted">{t(`panel.${section}.eyebrow`)}</p>
        <h2 className="my-1 font-display text-title">{t(`panel.${section}.titulo`)}</h2>
        <p className="m-0 text-small text-text-muted">{t(`panel.${section}.subtitulo`)}</p>
      </header>
      {/* Focusable so keyboard users can scroll a panel that has no controls of its own. */}
      <div
        tabIndex={0}
        role="region"
        aria-label={t(`panel.${section}.titulo`)}
        className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden p-4 focus-visible:-outline-offset-2"
      >
        {children}
      </div>
    </section>
  );
}
