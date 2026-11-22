import { t } from "../lib/copy";

// Credit bar at the foot of the app. Its height is --layout-credit-height, which the shell subtracts
// from the stage above, so it never covers map controls, the timeline or the MapLibre attribution.
export default function CreditBar() {
  return (
    <a
      href="https://darwingeospatial.com"
      target="_blank"
      rel="noopener noreferrer"
      aria-label={t("credito.enlace")}
      className="absolute inset-x-0 bottom-0 z-rail flex h-credit items-center justify-center gap-2 border-t border-line bg-panel text-caption text-text-muted no-underline hover:text-text focus-visible:-outline-offset-2"
    >
      <span>{t("credito.texto")}</span>
      <img
        src={`${import.meta.env.BASE_URL}darwin-logo.png`}
        alt=""
        aria-hidden="true"
        className="h-6 w-auto"
      />
    </a>
  );
}
