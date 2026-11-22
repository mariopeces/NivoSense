import * as maplibregl from "maplibre-gl";
import { t } from "./copy";
import type { Webcam } from "./types";
import { cameraName, fanOffsets, groupRadiusM, groupWebcams, isLive, placeName, type WebcamGroup } from "./webcams";

// Cameras are DOM markers, not a map layer: the browser paints them above the whole WebGL canvas, so no snow,
// RGB, SWE, basin or weather layer can ever cover one, whatever order those layers are added or reordered in.

// Lucide 0.460.0 'cctv' and 'camera-off' (ISC), the glyphs of docs/design/mockups/webcam-symbol.svg.
const GLYPHS = {
  live: '<path d="M16.75 12h3.632a1 1 0 0 1 .894 1.447l-2.034 4.069a1 1 0 0 1-1.708.134l-2.124-2.97"/><path d="M17.106 9.053a1 1 0 0 1 .447 1.341l-3.106 6.211a1 1 0 0 1-1.342.447L3.61 12.3a2.92 2.92 0 0 1-1.3-3.91L3.69 5.6a2.92 2.92 0 0 1 3.92-1.3z"/><path d="M2 19h3.76a2 2 0 0 0 1.8-1.1L9 15"/><path d="M2 21v-4"/><path d="M7 9h.01"/>',
  offline:
    '<line x1="2" x2="22" y1="2" y2="22"/><path d="M7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16"/><path d="M9.5 4h5L17 7h3a2 2 0 0 1 2 2v7.5"/><path d="M14.121 15.121A3 3 0 1 1 9.88 10.88"/>',
};

export function glyphSvg(state: "live" | "offline") {
  return `<svg class="webcam-glyph" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${GLYPHS[state]}</svg>`;
}

export type WebcamMarkers = {
  update: (webcams: Webcam[], selectedId: string | null) => void;
  destroy: () => void;
};

type Pin = { button: HTMLButtonElement; marker: maplibregl.Marker };

export function createWebcamMarkers(map: maplibregl.Map, onSelect: (id: string | null) => void): WebcamMarkers {
  let groups: WebcamGroup[] = [];
  let webcams: Webcam[] = [];
  let selectedId: string | null = null;
  let expandedId: string | null = null;
  const pins: Pin[] = [];
  const fan: Pin[] = [];
  let leaders: maplibregl.Marker | null = null;
  let originButton: HTMLButtonElement | null = null;

  const stateOf = (cams: Webcam[]) => (cams.some(isLive) ? "live" : "offline");
  const clearFan = () => {
    fan.splice(0).forEach((pin) => pin.marker.remove());
    leaders?.remove();
    leaders = null;
  };

  function button(state: "live" | "offline", label: string) {
    const el = document.createElement("button");
    el.type = "button";
    el.className = "webcam-pin";
    el.dataset.state = state;
    el.setAttribute("aria-label", label);
    el.innerHTML = glyphSvg(state);
    return el;
  }

  function collapse(returnFocus = false) {
    if (expandedId === null) return;
    expandedId = null;
    clearFan();
    pins.forEach((pin) => pin.button.setAttribute("aria-expanded", "false"));
    if (returnFocus) originButton?.focus();
    originButton = null;
  }

  function expand(group: WebcamGroup, origin: HTMLButtonElement) {
    collapse();
    expandedId = group.id;
    originButton = origin;
    origin.setAttribute("aria-expanded", "true");
    const offsets = fanOffsets(group.cams.length);
    const extent = offsets[0].radius + 32;

    // The leader lines are one SVG marker on the origin, so they follow it while the map pans.
    const svgNs = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNs, "svg");
    svg.setAttribute("class", "webcam-leaders");
    svg.setAttribute("width", String(extent * 2));
    svg.setAttribute("height", String(extent * 2));
    svg.setAttribute("aria-hidden", "true");
    offsets.forEach(({ dx, dy }) => {
      const line = document.createElementNS(svgNs, "line");
      line.setAttribute("x1", String(extent));
      line.setAttribute("y1", String(extent));
      line.setAttribute("x2", String(extent + dx));
      line.setAttribute("y2", String(extent + dy));
      svg.appendChild(line);
    });
    leaders = new maplibregl.Marker({ element: svg as unknown as HTMLElement, anchor: "center" })
      .setLngLat([group.longitude, group.latitude])
      .addTo(map);

    group.cams.forEach((cam, index) => {
      const live = isLive(cam);
      const el = button(live ? "live" : "offline", t("webcam.tooltip_simbolo", { nombre: cameraName(cam.name), estado: t(live ? "webcam.en_directo" : "webcam.sin_imagen") }));
      el.dataset.id = cam.id;
      el.classList.add("webcam-pin-sub");
      el.setAttribute("aria-pressed", String(cam.id === selectedId));
      el.title = cameraName(cam.name);
      el.addEventListener("click", (event) => {
        event.stopPropagation();
        onSelect(cam.id === selectedId ? null : cam.id);
      });
      const marker = new maplibregl.Marker({ element: el, anchor: "center", offset: [offsets[index].dx, offsets[index].dy] })
        .setLngLat([group.longitude, group.latitude])
        .addTo(map);
      fan.push({ button: el, marker });
    });
    // The fan opens from the keyboard too: focus lands on the first camera, Escape brings it back to the origin.
    fan[0]?.button.focus();
  }

  function render() {
    collapse();
    pins.splice(0).forEach((pin) => pin.marker.remove());
    for (const group of groups) {
      const single = group.cams.length === 1;
      const state = stateOf(group.cams);
      const first = group.cams[0];
      const label = single
        ? t("webcam.tooltip_simbolo", { nombre: cameraName(first.name), estado: t(state === "live" ? "webcam.en_directo" : "webcam.sin_imagen") })
        : t("webcam.grupo_aria", { n: group.cams.length, lugar: placeName(first.location ?? first.name) });
      const el = button(state, label);
      el.dataset.id = group.id;
      if (single) {
        el.title = cameraName(first.name);
        el.addEventListener("click", (event) => {
          event.stopPropagation();
          collapse();
          onSelect(first.id === selectedId ? null : first.id);
        });
      } else {
        el.classList.add("webcam-pin-group");
        el.setAttribute("aria-expanded", "false");
        const badge = document.createElement("span");
        badge.className = "webcam-badge";
        badge.textContent = String(group.cams.length);
        badge.setAttribute("aria-hidden", "true");
        el.appendChild(badge);
        el.addEventListener("click", (event) => {
          event.stopPropagation();
          if (expandedId === group.id) collapse();
          else expand(group, el);
        });
      }
      const marker = new maplibregl.Marker({ element: el, anchor: "center" })
        .setLngLat([group.longitude, group.latitude])
        .addTo(map);
      pins.push({ button: el, marker });
    }
    paintSelection();
  }

  function paintSelection() {
    pins.forEach((pin, index) => {
      const group = groups[index];
      const selected = group.cams.some((cam) => cam.id === selectedId);
      pin.button.classList.toggle("is-selected", selected);
      if (group.cams.length === 1) pin.button.setAttribute("aria-pressed", String(selected));
      pin.marker.getElement().style.zIndex = selected ? "2" : "1";
    });
    fan.forEach((pin) => {
      const selected = pin.button.dataset.id === selectedId;
      pin.button.classList.toggle("is-selected", selected);
      pin.button.setAttribute("aria-pressed", String(selected));
      pin.marker.getElement().style.zIndex = selected ? "4" : "3";
    });
    if (leaders) leaders.getElement().style.zIndex = "2";
  }

  // Groups depend on the zoom: points that overlap on screen share one marker, so the set is rebuilt after a zoom.
  function regroup() {
    const key = (list: WebcamGroup[]) => list.map((g) => `${g.id}:${g.cams.map((c) => `${c.id}${isLive(c)}`).join(",")}`).join("|");
    const next = groupWebcams(webcams, groupRadiusM(map.getZoom(), map.getCenter().lat));
    const changed = key(next) !== key(groups);
    groups = next;
    if (changed) render();
    else paintSelection();
  }

  const onMapClick = () => collapse();
  const onZoomStart = () => collapse();
  const onKey = (event: KeyboardEvent) => {
    if (event.key === "Escape") collapse(true);
  };
  map.on("click", onMapClick);
  map.on("zoomstart", onZoomStart);
  map.on("zoomend", regroup);
  document.addEventListener("keydown", onKey);

  return {
    update(next, nextSelected) {
      webcams = next;
      selectedId = nextSelected;
      regroup();
    },
    destroy() {
      map.off("click", onMapClick);
      map.off("zoomstart", onZoomStart);
      map.off("zoomend", regroup);
      document.removeEventListener("keydown", onKey);
      clearFan();
      pins.splice(0).forEach((pin) => pin.marker.remove());
    },
  };
}
