import type { LayerMode } from "./LeftRail";
import type { SnowOverlay } from "../lib/snowModel";
import type { WeatherOverlay, WeatherVariable } from "../lib/weather";

type Props = {
  layer: LayerMode;
  weatherOverlay: WeatherOverlay | null;
  snowOverlay: SnowOverlay | null;
};

const PANEL =
  "pointer-events-auto absolute bottom-4 right-4 z-20 w-[260px] rounded-xl border border-white/5 bg-[#081020]/85 px-4 py-3 backdrop-blur-xl shadow-[0_20px_40px_-12px_rgba(0,0,0,0.7)]";

const WEATHER_STYLE: Record<WeatherVariable, { title: string; gradient: string }> = {
  precipitation_total: {
    title: "Accumulated precipitation",
    gradient: "linear-gradient(to right, #082f49, #0e7490, #06b6d4, #22d3ee, #ecfeff)",
  },
  snowfall: {
    title: "Accumulated snowfall",
    gradient: "linear-gradient(to right, #2d236e, #4f46e5, #818cf8, #c7d2fe, #ffffff)",
  },
};

const MIN_VISIBLE_MM = 0.1;

function formatUtc(value: string) {
  return new Date(value).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  });
}

function formatResolution(degrees: number) {
  return `${degrees}° (~${Math.round(degrees * 111)} km)`;
}

function formatAge(runAt: string) {
  const hours = Math.max(0, Math.round((Date.now() - new Date(runAt).getTime()) / 3_600_000));
  return hours < 48 ? `${hours} h` : `${Math.round(hours / 24)} d`;
}

const SNOW_GRADIENTS = {
  swe: "linear-gradient(to right, #142163, #2f61d6, #60a5fa, #bae6fd, #ffffff)",
  depth: "linear-gradient(to right, #3c2878, #6366f1, #81b4fa, #cfe9fe, #ffffff)",
};

function SnowLegend({ overlay }: { overlay: SnowOverlay }) {
  const { info } = overlay;
  if (overlay.layer === "s2_true_colour") {
    return (
      <div className={PANEL}>
        <span className="text-[11px] uppercase tracking-[0.22em] text-slate-300">
          Sentinel-2 true colour, 10 m
        </span>
        <p className="mt-2 text-[11px] tabular-nums text-slate-400">
          {formatUtc(`${info.date}T11:00:00Z`).split(",")[0]} ·{" "}
          {Math.round((info.valid_fraction ?? 0) * 100)} % clear of clouds
        </p>
        <p className="mt-2 text-[10px] leading-snug text-slate-600">{info.source}</p>
      </div>
    );
  }
  if (overlay.layer === "observed_snow_10m") {
    return (
      <div className={PANEL}>
        <span className="text-[11px] uppercase tracking-[0.22em] text-slate-300">
          Observed snow, 10 m
        </span>
        <div className="mt-2.5 flex items-center gap-3 text-[11px] text-slate-400">
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm bg-cyan-300" /> Snow
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm bg-slate-500/60" /> Cloud or no data
          </span>
        </div>
        <p className="mt-2 text-[11px] tabular-nums text-slate-400">
          {formatUtc(`${info.date}T11:00:00Z`).split(",")[0]} ·{" "}
          {Math.round((info.valid_fraction ?? 0) * 100)} % clear ·{" "}
          {((info.snow_fraction_of_valid ?? 0) * 100).toFixed(1)} % of it snow
        </p>
        <p className="mt-2 text-[10px] leading-snug text-slate-600">{info.source}</p>
      </div>
    );
  }
  const unit = overlay.layer === "swe" ? "mm" : "m";
  const title = overlay.layer === "swe" ? "Snow water equivalent" : "Snow depth";
  return (
    <div className={PANEL}>
      <span className="text-[11px] uppercase tracking-[0.22em] text-slate-300">{title}</span>
      <div
        className="mt-2.5 h-2.5 w-full rounded-full"
        style={{ background: SNOW_GRADIENTS[overlay.layer] }}
      />
      <div className="mt-2 flex justify-between text-[11px] tabular-nums text-slate-500">
        <span>
          {info.minimum_visible} {unit}
        </span>
        <span>
          {info.scale_max} {unit}
        </span>
      </div>
      <p className="mt-2 text-[11px] tabular-nums text-slate-400">
        Weighted ensemble mean, {formatUtc(`${info.date}T00:00:00Z`).split(",")[0]} (UTC)
      </p>
      <p className="mt-1 text-[10px] leading-snug text-amber-300/80">
        Experimental: magnitudes are not verified against in-situ measurements.
      </p>
    </div>
  );
}

export default function Legend({ layer, weatherOverlay, snowOverlay }: Props) {
  if (!weatherOverlay && snowOverlay) {
    return <SnowLegend overlay={snowOverlay} />;
  }
  if (weatherOverlay) {
    const style = WEATHER_STYLE[weatherOverlay.variable];
    return (
      <div className={PANEL}>
        <span className="text-[11px] uppercase tracking-[0.22em] text-slate-300">
          {style.title}
        </span>
        <div
          className="mt-2.5 h-2.5 w-full rounded-full"
          style={{ background: style.gradient }}
        />
        <div className="mt-2 flex justify-between text-[11px] tabular-nums text-slate-500">
          <span>{MIN_VISIBLE_MM} mm</span>
          <span>{weatherOverlay.scaleMaxMm.toFixed(1)} mm</span>
        </div>
        <p className="mt-2 text-[11px] text-slate-400">
          {weatherOverlay.regionMaxMm < MIN_VISIBLE_MM
            ? `No values above ${MIN_VISIBLE_MM} mm in the region`
            : `Regional maximum ${weatherOverlay.regionMaxMm.toFixed(1)} mm`}
          <span className="text-slate-600"> · water equivalent</span>
        </p>
        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 border-t border-white/5 pt-2 text-[11px] text-slate-500">
          <dt>Model</dt>
          <dd className="text-right text-slate-300">{weatherOverlay.modelName}</dd>
          <dt>Resolution</dt>
          <dd className="text-right tabular-nums text-slate-300">
            {formatResolution(weatherOverlay.gridDegrees)}
          </dd>
          <dt>Cycle (UTC)</dt>
          <dd className="text-right tabular-nums text-slate-300">
            {formatUtc(weatherOverlay.runAt)} · {formatAge(weatherOverlay.runAt)} old
          </dd>
          <dt>Valid (UTC)</dt>
          <dd className="text-right tabular-nums text-slate-300">
            {formatUtc(weatherOverlay.validAt)}
          </dd>
        </dl>
        {weatherOverlay.note && (
          <p className="mt-2 text-[10px] leading-snug text-amber-300/80">
            {weatherOverlay.note}
          </p>
        )}
        <p className="mt-2 text-[10px] text-slate-600">{weatherOverlay.attribution}</p>
      </div>
    );
  }
  const config =
    layer === "cover"
      ? {
          title: "Snow cover",
          gradient:
            "linear-gradient(to right, #0f172a, #155e75, #22d3ee, #ecfeff)",
          left: "0%",
          right: "100%",
        }
      : {
          title: "Snow change",
          gradient:
            "linear-gradient(to right, #f87171, #1e293b, #67e8f9)",
          left: "−",
          right: "+",
        };

  return (
    <div className={PANEL}>
      <div className="flex items-center justify-between">
        <span className="text-[11px] uppercase tracking-[0.22em] text-slate-300">
          {config.title}
        </span>
      </div>
      <div
        className="mt-2.5 h-2.5 w-full rounded-full"
        style={{ background: config.gradient }}
      />
      <div className="mt-2 flex justify-between text-[11px] tabular-nums text-slate-500">
        <span>{config.left}</span>
        <span>{config.right}</span>
      </div>
    </div>
  );
}
