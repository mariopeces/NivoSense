import { CameraOff } from "lucide-react";
import { Icon } from "../lib/icons";
import { t } from "../lib/copy";
import { fechaCorta, horaMadrid } from "../lib/format";
import type { Webcam } from "../lib/types";
import { GroupLabel, Notice, Skeleton } from "./ui";

type Props = {
  webcams: Webcam[];
  loading: boolean;
  error: string | null;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
};

export default function WebcamsSection({ webcams, loading, error, selectedId, onSelect }: Props) {
  if (loading) return <Skeleton label={t("cargando.capa", { capa: t("capa.webcams.nombre") })} />;
  if (error) return <Notice error title={t("error.webcams")} />;

  const sorted = [...webcams].sort(byRoadPoint);
  const live = sorted.filter((cam) => !cam.offline && safeImageUrl(cam.image_url));
  const offline = sorted.filter((cam) => !live.includes(cam));
  const list = (cams: Webcam[]) => (
    <ul className="m-0 list-none p-0">
      {cams.map((cam) => (
        <WebcamRow
          key={cam.id}
          webcam={cam}
          live={live.includes(cam)}
          selected={cam.id === selectedId}
          onSelect={onSelect}
        />
      ))}
    </ul>
  );

  return (
    <>
      <GroupLabel>
        {t("webcam.lista_vivas")} <span className="tnum">({live.length})</span>
      </GroupLabel>
      {live.length ? list(live) : <p className="mx-1 mt-0 text-small text-text-muted">{t("vacio.sin_webcams")}</p>}
      {offline.length > 0 && (
        <>
          <GroupLabel>
            {t("webcam.lista_sin_imagen")} <span className="tnum">({offline.length})</span>
          </GroupLabel>
          {list(offline)}
        </>
      )}
    </>
  );
}

function WebcamRow({
  webcam,
  live,
  selected,
  onSelect,
}: {
  webcam: Webcam;
  live: boolean;
  selected: boolean;
  onSelect: (id: string | null) => void;
}) {
  const imageUrl = live ? safeImageUrl(webcam.image_url) : null;
  return (
    <li className="border-b border-line">
      <button
        type="button"
        aria-pressed={selected}
        onClick={() => onSelect(selected ? null : webcam.id)}
        className={`flex w-full items-center gap-3 px-1 py-2 text-left hover:bg-panel-soft ${
          selected ? "shadow-[inset_3px_0_0_var(--color-accent)]" : ""
        }`}
      >
        <span
          aria-hidden="true"
          className={`h-2 w-2 flex-none rounded-full ${live ? "bg-live" : "border-[1.5px] border-text-muted"}`}
        />
        <span className="min-w-0 flex-1">
          <span className="tnum block">{cameraName(webcam.name)}</span>
          {webcam.location && (
            <span className="block text-small text-text-muted">{placeName(webcam.location)}</span>
          )}
        </span>
        <span className={`text-caption ${live ? "text-live" : "text-text-muted"}`}>
          {t(live ? "webcam.en_directo" : "webcam.sin_imagen")}
        </span>
      </button>
      {selected && (
        <div className="mb-3 overflow-hidden rounded-lg border border-line">
          {imageUrl ? (
            <img
              src={imageUrl}
              alt={cameraName(webcam.name)}
              className="aspect-video w-full bg-panel-soft object-cover"
              loading="lazy"
              referrerPolicy="no-referrer"
              onError={(event) => {
                event.currentTarget.hidden = true;
              }}
            />
          ) : (
            <div className="grid aspect-video place-items-center bg-panel-soft p-6 text-center text-text-muted">
              <div>
                <Icon icon={CameraOff} />
                <p className="mb-1 mt-2 font-medium text-text">{t("webcam.offline_titulo")}</p>
                <p className="m-0 text-small">{t("webcam.offline_detalle")}</p>
              </div>
            </div>
          )}
          <div className="px-4 pb-4 pt-3 text-small">
            {imageUrl && webcam.captured_at && (
              <p className="tnum m-0">
                {t("webcam.capturada", {
                  fecha_corta: fechaCorta(webcam.captured_at),
                  hora: horaMadrid(webcam.captured_at),
                })}
              </p>
            )}
            <a
              href={webcam.source_url}
              target="_blank"
              rel="noreferrer"
              className="mt-2 inline-block text-caption text-text-muted underline"
            >
              {webcam.attribution}
            </a>
          </div>
        </div>
      )}
    </li>
  );
}

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

function safeImageUrl(value: string | null) {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}
