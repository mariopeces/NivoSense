import { CameraOff, Clock, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Icon } from "../lib/icons";
import { t } from "../lib/copy";
import type { Webcam } from "../lib/types";
import { ageMinutes, cameraImage, cameraName, captureAge, captureTime, placeName, STALE_HOURS } from "../lib/webcams";

type Props = {
  webcam: Webcam | null;
  mobile: boolean;
  /** Map pixels covered by the sheet and timeline on mobile; the card sits above them. */
  bottom: number;
  onClose: () => void;
};

// The card of the selected camera, over the map: top right below the map controls on desktop, a full-width
// card above the sheet on mobile. Escape and the close button dismiss it.
export default function WebcamCard({ webcam, mobile, bottom, onClose }: Props) {
  useEffect(() => {
    if (!webcam) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [webcam, onClose]);

  if (!webcam) return null;
  return <Card key={webcam.id} webcam={webcam} mobile={mobile} bottom={bottom} onClose={onClose} />;
}

function Card({ webcam, mobile, bottom, onClose }: Omit<Props, "webcam"> & { webcam: Webcam }) {
  const [failed, setFailed] = useState(false);
  const image = failed ? null : cameraImage(webcam);
  const stale = image && webcam.captured_at ? ageMinutes(webcam.captured_at) > STALE_HOURS * 60 : false;
  const place = webcam.location ? placeName(webcam.location) : null;

  return (
    <section
      aria-label={cameraName(webcam.name)}
      className={`absolute z-popover overflow-y-auto rounded-lg bg-panel shadow-popover ${
        mobile ? "inset-x-2 max-h-[55%]" : "right-4 top-[148px] max-h-[calc(100%-260px)] w-[360px]"
      }`}
      style={mobile ? { bottom } : undefined}
    >
      <div className="flex items-start gap-3 px-4 pb-2 pt-3">
        <div className="min-w-0 flex-1">
          <h3 className="tnum m-0 text-body font-medium">{cameraName(webcam.name)}</h3>
          {place && <p className="m-0 text-small text-text-muted">{place}</p>}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={t("webcam.cerrar")}
          className="-mr-2 -mt-1 grid h-11 w-11 flex-none place-items-center rounded-md text-text-muted hover:bg-panel-soft md:h-9 md:w-9"
        >
          <Icon icon={X} />
        </button>
      </div>
      {image ? (
        <img
          src={image}
          alt={cameraName(webcam.name)}
          className="aspect-video w-full bg-panel-soft object-cover"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
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
      <div className="grid gap-1 px-4 pb-4 pt-3 text-small">
        {image && webcam.captured_at ? (
          <p className="tnum m-0">
            {captureTime(webcam.captured_at)} · {captureAge(webcam.captured_at)}
          </p>
        ) : (
          <p className="m-0 text-text-muted">{t("webcam.offline_ultima_desconocida")}</p>
        )}
        {stale && (
          <p className="m-0 flex items-center gap-1 text-warning">
            <Icon icon={Clock} />
            {t("webcam.imagen_antigua", { horas: STALE_HOURS })}
          </p>
        )}
        <a href={webcam.source_url} target="_blank" rel="noreferrer" className="text-caption text-text-muted underline">
          {webcam.attribution}
        </a>
      </div>
    </section>
  );
}
