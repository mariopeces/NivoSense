import { t } from "../lib/copy";
import type { Webcam } from "../lib/types";
import { glyphSvg } from "../lib/webcamMarkers";
import { isLive, isMapped } from "../lib/webcams";
import { Notice, Skeleton } from "./ui";

type Props = {
  webcams: Webcam[];
  loading: boolean;
  error: string | null;
};

// The cameras live on the map only; the panel says how many there are and how to read the symbols.
export default function WebcamsSection({ webcams, loading, error }: Props) {
  if (loading) return <Skeleton label={t("cargando.capa", { capa: t("capa.webcams.nombre") })} />;
  if (error) return <Notice error title={t("error.webcams")} />;

  const withImage = webcams.filter((cam) => isMapped(cam) && isLive(cam)).length;
  const unplaced = webcams.filter((cam) => !isMapped(cam)).length;

  return (
    <div className="grid gap-3">
      <p className="tnum m-0 font-medium">
        {withImage === 0
          ? t("vacio.sin_webcams")
          : withImage === 1
            ? t("webcam.contador_una")
            : t("webcam.contador", { n: withImage })}
      </p>
      {unplaced > 0 && <p className="tnum m-0 text-small text-text-muted">{t("webcam.sin_posicion", { n: unplaced })}</p>}
      <ul className="m-0 grid list-none gap-2 p-0 text-small">
        <li className="flex items-center gap-3">
          <Symbol state="live" />
          {t("webcam.lista_vivas")}
        </li>
        <li className="flex items-center gap-3">
          <Symbol state="offline" />
          {t("webcam.sin_imagen")}
        </li>
      </ul>
      <p className="m-0 text-small text-text-muted">{t("webcam.leyenda_grupo")}</p>
    </div>
  );
}

// The same disc the map draws, not interactive.
function Symbol({ state }: { state: "live" | "offline" }) {
  return (
    <span
      aria-hidden="true"
      className="webcam-pin relative !h-7 !w-7 flex-none !cursor-default"
      data-state={state}
      dangerouslySetInnerHTML={{ __html: glyphSvg(state) }}
    />
  );
}
