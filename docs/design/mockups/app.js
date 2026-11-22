// Static mockup renderer. Reads the spec files (tokens, ramps, copy) and real repo data only.
const REPO = '../../../';
const q = new URLSearchParams(location.search);
const SCREEN = q.get('s') || 'nieve';
const MOBILE = window.matchMedia('(max-width: 767px)').matches;

// The one real scene used to show a filled state: Copernicus Sentinel-2 L1C TCI of 2026-02-21,
// window over the Veleta-Mulhacen crest (docs/design/tools/fetch_backgrounds.py). Corners in EPSG:4326.
const SCENE = {
  date: '2026-02-21',
  img: 'data/l1c_tci_20260221.jpg',
  corners: [[-3.54062, 37.16217], [-3.18021, 37.16327], [-3.17978, 36.98299], [-3.53934, 36.9819]],
};
const TODAY = '2026-11-22';
// Forecast slot after today. Length here = the 5-day horizon the live site's forecast buttons offer today;
// in production it is the last forecast date in catalog/index.json.
const FORECAST_DAYS = 5;
const STALE_HOURS = 2;
// Lucide 0.460.0 'cctv' paths, used inside the map symbol so the spec SVG and the mockup draw the same glyph.
const CCTV_PATHS = ['M16.75 12h3.632a1 1 0 0 1 .894 1.447l-2.034 4.069a1 1 0 0 1-1.708.134l-2.124-2.97', 'M17.106 9.053a1 1 0 0 1 .447 1.341l-3.106 6.211a1 1 0 0 1-1.342.447L3.61 12.3a2.92 2.92 0 0 1-1.3-3.91L3.69 5.6a2.92 2.92 0 0 1 3.92-1.3z', 'M2 19h3.76a2 2 0 0 0 1.8-1.1L9 15', 'M2 21v-4', 'M7 9h.01'];
const SEASON_START = '2025-10-01';

const BASIN_NAMES = {
  'RIO GUADALQUIVIR': 'Río Guadalquivir',
  'RIO GUADALFEO O RIO CADIAR': 'Río Guadalfeo o Río Cádiar',
  'RIO ADRA O GRANDE O VERDE': 'Río Adra o Grande o Verde',
  'RIO ANDARAX': 'Río Andarax',
};
const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
const DIAS = ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb'];

const SCREENS = {
  nieve: { section: 'nieve', scene: true, sheet: 'peek' },
  capas: { section: 'nieve', scene: true, sheet: 'half' },
  'nieve-info': { section: 'nieve', scene: true, sheet: 'half' },
  colapsado: { section: 'nieve', scene: true, collapsed: true, sheet: 'peek' },
  timeline: { section: 'nieve', scene: true, sheet: 'peek', tooltip: true },
  agua: { section: 'agua', scene: true, sheet: 'half' },
  cuenca: { section: 'agua', scene: true, basin: 'RIO GUADALFEO O RIO CADIAR', sheet: 'full' },
  webcams: { section: 'webcams', scene: true, sheet: 'peek', card: 'offline' },
  'webcam-live': { section: 'webcams', scene: true, sheet: 'peek', card: 'live' },
  metodo: { section: 'metodo', doc: true },
  'timeline-estados': { section: 'nieve', doc: true, specimen: true },
  vacio: { section: 'nieve', scene: false, sheet: 'half', state: 'empty' },
  cargando: { section: 'nieve', scene: false, sheet: 'half', state: 'loading' },
  error: { section: 'nieve', scene: false, sheet: 'half', state: 'error' },
};
const S = SCREENS[SCREEN];

let T, R, C;
const $ = (sel) => document.querySelector(sel);
const get = (obj, path) => path.split('.').reduce((o, k) => (o == null ? o : o[k]), obj);
const t = (path, vars = {}) => (get(C, path) || `[${path}]`).replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? `{${k}}`);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const tok = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function fechaCorta(iso) {
  const d = new Date(iso + 'T12:00:00Z');
  return `${d.getUTCDate()} ${MESES[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}
function fechaConDia(iso) {
  const d = new Date(iso + 'T12:00:00Z');
  return `${DIAS[d.getUTCDay()]} ${fechaCorta(iso)}`;
}
const MESES_LARGOS = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];
const DIAS_LARGOS = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];
function fechaLarga(iso) {
  const d = new Date(iso + 'T12:00:00Z');
  return `${DIAS_LARGOS[d.getUTCDay()]} ${d.getUTCDate()} de ${MESES_LARGOS[d.getUTCMonth()]} de ${d.getUTCFullYear()}`;
}
function edad(ms, date) {
  // copy formats.edad
  const min = Math.floor(ms / 60000);
  if (min < 1) return t('webcam.edad_ahora');
  if (min < 60) return t('webcam.edad_min', { n: min });
  const h = Math.floor(min / 60);
  if (h < 24) return t('webcam.edad_h', { n: h });
  const d = Math.floor(h / 24);
  if (d === 1) return t('webcam.edad_dia');
  if (d <= 7) return t('webcam.edad_dias', { n: d });
  return fechaCorta(new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Madrid' }).format(date));
}
function numEs(v, dec = 1) {
  return v.toLocaleString('es-ES', { minimumFractionDigits: dec, maximumFractionDigits: dec });
}

function applyTokens(tokens) {
  const root = document.documentElement.style;
  const flat = (obj, prefix) => {
    for (const [k, v] of Object.entries(obj)) {
      if (k.startsWith('$')) continue;
      if (v && typeof v === 'object' && '$value' in v) {
        let val = v.$value;
        if (Array.isArray(val)) val = prefix.startsWith('motion-easing') ? `cubic-bezier(${val.join(',')})` : val.map((f) => (f.includes(' ') ? `'${f}'` : f)).join(', ');
        if (val && typeof val === 'object') {
          for (const [kk, vv] of Object.entries(val)) {
            if (kk === 'family') root.setProperty(`--${prefix}${k}-family`, `var(--font-family-${vv})`);
            else if (kk === 'size') root.setProperty(`--${prefix}${k}-size`, `${vv}px`);
            else if (kk === 'lineHeight') root.setProperty(`--${prefix}${k}-lh`, `${vv}px`);
            else root.setProperty(`--${prefix}${k}-${kk}`, vv);
          }
        } else root.setProperty(`--${prefix}${k}`, val);
      } else if (v && typeof v === 'object') flat(v, `${prefix}${k}-`);
    }
  };
  flat(tokens, '');
}

function icon(name, size = 16) {
  return `<i data-lucide="${name}" data-size="${size}"></i>`;
}
function drawIcons() {
  lucide.createIcons();
  // Constant 1.75 px stroke at any size (tokens.icon.stroke).
  document.querySelectorAll('svg.lucide').forEach((svg) => {
    const host = svg;
    const size = Number(host.getAttribute('data-size') || (host.closest('.rail-btn') ? 20 : 16));
    svg.setAttribute('width', size);
    svg.setAttribute('height', size);
    svg.setAttribute('stroke-width', ((1.75 * 24) / size).toFixed(3));
    svg.setAttribute('aria-hidden', 'true');
  });
}

function fillCopy() {
  document.querySelectorAll('[data-copy]').forEach((el) => (el.textContent = t(el.dataset.copy)));
  document.querySelectorAll('[data-copy-label]').forEach((el) => {
    el.setAttribute('aria-label', t(el.dataset.copyLabel));
    el.title = t(el.dataset.copyLabel);
  });
  document.querySelectorAll('.rail-btn[data-section]').forEach((b) => {
    b.title = t(`rail.tooltip_${b.dataset.section}`);
    if (b.dataset.section === S.section) {
      b.classList.add('active');
      b.setAttribute('aria-current', 'page');
    }
  });
}

/* ---------- legends from ramps.json ---------- */
function rgba(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
}
function patternSwatch(cls) {
  const c = document.createElement('canvas');
  c.width = 16; c.height = 16;
  const g = c.getContext('2d');
  if (cls.color) { g.fillStyle = rgba(cls.color, cls.alpha || 1); g.fillRect(0, 0, 16, 16); }
  const p = cls.pattern;
  if (p) {
    g.fillStyle = g.strokeStyle = rgba(p.color, p.alpha ?? 1);
    if (p.kind === 'dots') for (let y = 3; y < 16; y += p.spacing_px) for (let x = 3; x < 16; x += p.spacing_px) { g.beginPath(); g.arc(x, y, p.radius_px, 0, 7); g.fill(); }
    else { g.lineWidth = p.width_px; for (let k = -16; k < 16; k += p.spacing_px) { g.beginPath(); g.moveTo(k, 16); g.lineTo(k + 16, 0); g.stroke(); } }
  }
  return c;
}
function legendHTML(layerId) {
  const L = R.layers[layerId];
  if (L.categorical) {
    return `<div class="legend-cat" data-cat="${layerId}">${L.classes.map((c, i) => `<div data-i="${i}"><span class="slot"></span>${esc(c.label_es)}</div>`).join('')}</div>`;
  }
  const cls = L.classes;
  const steps = cls.map((c) => (c.color ? `<span style="background:${rgba(c.color, c.alpha)}"></span>` : `<span class="none"></span>`)).join('');
  const bounds = [cls[0].min, ...cls.map((c) => c.max).filter((v) => v != null)];
  const fmt = (v) => (L.unit === '%' ? Math.round(v * 100) : v);
  const labels = bounds.map((b) => `<span>${fmt(b)}</span>`).join('');
  const unitKey = { snow_cover_probability: 'leyenda.probabilidad', swe: 'leyenda.swe', snow_depth: 'leyenda.espesor' }[layerId];
  const transp = { snow_cover_probability: 'leyenda.transparente_probabilidad', swe: 'leyenda.transparente_swe' }[layerId];
  return `<div class="legend-steps">${steps}</div><div class="legend-labels">${labels}</div>
    <div class="legend-unit">${esc(t(unitKey))}${transp ? ' · ' + esc(t(transp)) : ''}</div>`;
}
function hydrateLegends() {
  document.querySelectorAll('[data-cat]').forEach((el) => {
    const L = R.layers[el.dataset.cat];
    el.querySelectorAll('[data-i]').forEach((row) => {
      const cv = patternSwatch(L.classes[Number(row.dataset.i)]);
      row.querySelector('.slot').replaceWith(cv);
    });
  });
}

/* ---------- panel content ---------- */
function badge(estado) {
  return `<span class="badge ${estado}" title="${esc(t('estado.tooltip_' + estado))}"><span class="glyph"></span>${esc(t('estado.' + estado))}</span>`;
}
function layerRow({ key, ramp, on = false, pending = false, expanded = false, date, opacity = 100, info = false }) {
  const c = get(C, `capa.${key}`);
  const name = c.nombre;
  const estado = pending ? 'pendiente' : c.estado;
  const meta = c.resolucion ? t('fila_capa.meta', { fuente: c.fuente, resolucion: c.resolucion }) : c.fuente;
  const toggle = `<button class="icon-btn ${on ? 'on' : ''}" ${pending ? 'disabled aria-disabled="true"' : ''} aria-pressed="${on}" aria-label="${esc(t(on ? 'fila_capa.ocultar' : 'fila_capa.mostrar', { capa: name }))}">${icon(on ? 'eye' : 'eye-off')}</button>`;
  const infoBtn = `<button class="icon-btn" aria-label="${esc(t('fila_capa.info', { capa: name }))}" ${info ? 'data-info-anchor' : ''}>${icon('info')}</button>`;
  const dateLine = date ? `<div class="layer-date num">${esc(date)}</div>` : '';
  const pend = pending && expanded ? `<div class="pending-note">${esc(t('fila_capa.pendiente_detalle'))}</div>` : '';
  let sub = '';
  if (expanded && ramp) {
    sub = `<div class="layer-sub">${legendHTML(ramp)}
      <label class="opacity"><span>${esc(t('fila_capa.opacidad'))}</span><input type="range" min="0" max="100" value="${opacity}" ${pending ? 'disabled' : ''}><span class="num">${esc(t('fila_capa.opacidad_valor', { valor: opacity }))}</span></label></div>`;
  } else if (expanded) {
    sub = `<div class="layer-sub"><label class="opacity"><span>${esc(t('fila_capa.opacidad'))}</span><input type="range" min="0" max="100" value="${opacity}"><span class="num">${esc(t('fila_capa.opacidad_valor', { valor: opacity }))}</span></label></div>`;
  }
  return `<div class="layer ${on ? 'on' : ''} ${pending ? 'pending' : ''}">
    <div class="layer-main">${toggle}<div class="layer-text"><div class="layer-name">${esc(name)}</div><div class="layer-meta">${esc(meta)}</div>${dateLine}${pend}<div style="margin-top:var(--space-2)">${badge(estado)}</div></div>${infoBtn}</div>${sub}</div>`;
}

function panelNieve() {
  const expandAll = SCREEN === 'capas';
  const sceneDate = t('fila_capa.fecha_observacion', { fecha_corta: fechaCorta(SCENE.date) });
  let notice = '';
  if (S.state === 'empty') notice = `<div class="notice"><h4>${esc(t('vacio.sin_catalogo_titulo'))}</h4><p>${esc(t('vacio.sin_catalogo_detalle'))}</p></div>`;
  if (S.state === 'error') notice = `<div class="notice error" role="alert"><h4>${esc(t('error.catalogo_titulo'))}</h4><p>${esc(t('error.catalogo_detalle'))}</p><button class="btn">${icon('rotate-cw')}${esc(t('error.reintentar'))}</button></div>`;
  if (S.state === 'loading') {
    return `<div class="group-label" aria-live="polite">${esc(t('cargando.catalogo'))}</div>` + '<div class="skeleton"></div>'.repeat(5);
  }
  const rgb = S.scene
    ? layerRow({ key: 'color_real', on: true, expanded: true, date: sceneDate, info: true })
    : layerRow({ key: 'color_real', pending: true });
  return `${notice}
    <div class="group-label">${esc(t('panel.grupo_capas_nieve'))}</div>
    ${layerRow({ key: 'nieve_observada', ramp: 'snow_cover_observed', pending: true, expanded: SCREEN === 'nieve' || expandAll })}
    ${layerRow({ key: 'nieve_diaria', ramp: 'snow_cover_probability', pending: true, expanded: expandAll })}
    ${layerRow({ key: 'swe', ramp: 'swe', pending: true, expanded: expandAll })}
    ${layerRow({ key: 'espesor', ramp: 'snow_depth', pending: true, expanded: expandAll })}
    <div class="group-label">${esc(t('panel.grupo_imagen'))}</div>
    ${rgb}
    <div class="group-label">${esc(t('panel.grupo_referencia'))}</div>
    ${layerRow({ key: 'cuencas', on: true })}
    ${layerRow({ key: 'webcams', on: true })}`;
}

let BASINS, CAMS, PASSES, FLOW_GUADALFEO, CETURSA;

function panelAgua() {
  const feats = [...BASINS.features].sort((a, b) => b.properties.area_km2 - a.properties.area_km2);
  if (S.basin) {
    const f = feats.find((x) => x.properties.nom_rio_1 === S.basin);
    const p = f.properties;
    return `<button class="back">${icon('arrow-left')}${esc(t('cuenca.volver'))}</button>
      <h2 class="title" style="margin-top:0">${esc(BASIN_NAMES[p.nom_rio_1])}</h2>
      <div class="kv">
        <div><div class="k">${esc(t('cuenca.area'))}</div><div class="v">${numEs(p.area_km2)} km²</div><div class="k">${esc(t('cuenca.area_valor', { valor: '' }).replace(/^\s*km²\s*/, ''))}</div></div>
        <div><div class="k">${esc(t('cuenca.nieve_area'))}</div><div class="v pending">${badge('pendiente')}</div></div>
        <div><div class="k">${esc(t('cuenca.swe_medio'))}</div><div class="v pending">${badge('pendiente')}</div></div>
        <div><div class="k">${esc(t('cuenca.espesor_medio'))}</div><div class="v pending">${badge('pendiente')}</div></div>
      </div>
      ${emptyChart(t('cuenca.grafico_titulo_nieve'), t('cuenca.pendiente_nieve_area'))}
      ${emptyChart(t('cuenca.grafico_titulo_swe'), t('cuenca.pendiente_detalle'))}
      <div class="chart"><h4>${esc(t('caudal.titulo'))} (${esc(t('caudal.unidad'))})</h4>
        <div class="small">${esc(t('caudal.estacion', { nombre: FLOW_GUADALFEO.station_name }))} · ${esc(FLOW_GUADALFEO.river_name)}</div>
        <div class="small muted">${esc(t('caudal.fuente_hidrosur'))}</div>
        <div style="margin-top:var(--space-2)">${badge('pendiente')}</div>
        <div class="pending-note">${esc(t('caudal.pendiente_detalle'))}</div></div>`;
  }
  return `<div class="group-label">${esc(t('cuenca.lista_titulo'))}</div>
    ${feats.map((f) => `<button class="basin-row"><span>${esc(BASIN_NAMES[f.properties.nom_rio_1])}</span><span class="small muted num">${numEs(f.properties.area_km2)} km²</span></button>`).join('')}
    <p class="small muted">${esc(t('cuenca.seleccionar'))}</p>`;
}

function emptyChart(title, note) {
  // Axes for the hydrological year with no series: the season curve appears when data exists.
  const months = ['oct', 'nov', 'dic', 'ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep'];
  const w = 268, h = 120, x0 = 8, x1 = w - 8, y1 = h - 22;
  const ticks = months.map((m, i) => {
    const x = x0 + ((x1 - x0) * (i + 0.5)) / 12;
    return i % 2 === 0 ? `<text x="${x}" y="${h - 6}" text-anchor="middle" font-size="12" fill="var(--color-text-muted)">${m}</text>` : '';
  }).join('');
  return `<div class="chart"><h4>${esc(title)}</h4>
    <svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(title)}: ${esc(note)}">
      <line x1="${x0}" y1="${y1}" x2="${x1}" y2="${y1}" stroke="var(--color-line-strong)"/>
      ${[0.33, 0.66].map((f) => `<line x1="${x0}" y1="${y1 * f}" x2="${x1}" y2="${y1 * f}" stroke="var(--color-line)"/>`).join('')}
      ${ticks}
      <text x="${w / 2}" y="${y1 / 2 + 4}" text-anchor="middle" font-size="13" fill="var(--color-text-muted)">${esc(t('cuenca.pendiente'))}</text>
    </svg>
    <div class="key"><span><i></i>${esc(t('cuenca.esta_temporada'))}</span><span><i class="prev"></i>${esc(t('cuenca.temporada_anterior'))}</span></div>
    <div class="pending-note">${esc(note)}</div></div>`;
}

function panelWebcams() {
  const pk = (c) => parseFloat((c.name.match(/PK ([0-9.]+)/) || [0, 0])[1]);
  const off = CAMS.filter((c) => c.offline).sort((a, b) => pk(a) - pk(b));
  const live = CAMS.filter((c) => !c.offline);
  return `<div class="group-label">${esc(t('webcam.lista_vivas'))} (${live.length})</div>
    ${live.length ? '' : `<p class="small muted">${esc(t('vacio.sin_webcams'))}</p>`}
    <div class="group-label">${esc(t('webcam.lista_sin_imagen'))} (${off.length})</div>
    ${off.map((c) => `<div class="cam-row"><span class="cam-dot off" aria-hidden="true"></span><span class="name num">${esc(camName(c))}</span><span class="small muted">DGT</span></div>`).join('')}
    <div class="group-label" style="margin-top:var(--space-4)">${esc(t('webcam.proveedor_cetursa'))}</div>
    <div class="layer pending"><div class="layer-main"><div class="layer-text"><div class="layer-name">${esc(t('webcam.cetursa_alta_pendiente'))}</div><div class="pending-note">${esc(t('webcam.cetursa_alta_pendiente_detalle'))}</div><div style="margin-top:var(--space-2)">${badge('pendiente')}</div></div></div></div>
    <div class="cone-legend">${coneGlyph()}<span class="small">${esc(t('webcam.leyenda_cono'))}</span>
      <span class="cam-sym off">${icon('camera-off', 14)}</span><span class="small">${esc(t('webcam.leyenda_sin_imagen'))}</span>
      <span class="cam-sym">${icon('cctv', 14)}</span><span class="small">${esc(t('webcam.leyenda_sin_orientacion'))}</span></div>`;
}
function camName(c) {
  // es-ES decimal comma in kilometre points (copy formats.numero).
  return c.name.replace(/PK (\d+)\.(\d+)/, 'PK $1,$2');
}
function cctvGlyph(cx, cy, size, color) {
  const k = size / 24;
  return `<g transform="translate(${cx - size / 2} ${cy - size / 2}) scale(${k})" fill="none" stroke="${color}" stroke-width="${(1.75 / k).toFixed(2)}" stroke-linecap="round" stroke-linejoin="round">${CCTV_PATHS.map((d) => `<path d="${d}"/>`).join('')}</g>`;
}
function coneGlyph() {
  // Symbolic glyph only: not a real camera's bearing.
  return `<svg width="48" height="40" viewBox="0 0 48 40" aria-hidden="true">
    <path d="M12 28 L44 8 A38 38 0 0 1 46 30 Z" fill="var(--color-ink)" fill-opacity="0.14" stroke="var(--color-ink)" stroke-width="1.25" stroke-linejoin="round"/>
    <g transform="translate(12 28) rotate(75)"><path d="M0 -17 L-4.5 -8 L4.5 -8 Z" fill="var(--color-ink)" stroke="var(--color-map-halo)" stroke-width="1.5" stroke-linejoin="round"/></g>
    <circle cx="12" cy="28" r="10" fill="var(--color-ink)" stroke="var(--color-map-halo)" stroke-width="2"/>
    ${cctvGlyph(12, 28, 12, 'var(--color-on-ink-strong)')}</svg>`;
}

function panelMetodo() { return ''; }

function renderPanel() {
  const sec = S.section;
  $('#eyebrow').textContent = t(`panel.${sec}.eyebrow`);
  $('#ptitle').textContent = t(`panel.${sec}.titulo`);
  $('#psub').textContent = t(`panel.${sec}.subtitulo`);
  const body = { nieve: panelNieve, agua: panelAgua, webcams: panelWebcams, metodo: panelMetodo }[sec]();
  $('#pbody').innerHTML = body;
  if (S.collapsed) {
    $('#app').classList.add('collapsed');
    const b = $('#collapse');
    b.innerHTML = `${icon('panel-left-open', 20)}<span>${esc(t('rail.mostrar_panel'))}</span>`;
    b.title = t('rail.tooltip_mostrar_panel');
  } else {
    $('#collapse').title = t('rail.tooltip_ocultar_panel');
  }
  if (MOBILE && S.card) $('#panel').style.display = 'none';
  if (MOBILE) {
    const h = { peek: 'var(--layout-sheet-peek)', half: 'var(--layout-sheet-half)', full: 'calc(100% - var(--layout-tabbar-height) - var(--space-12))' }[S.sheet || 'peek'];
    document.documentElement.style.setProperty('--sheet-height', h);
  }
}

/* ---------- timeline ---------- */
function dayIndex(iso) { return Math.round((Date.parse(iso) - Date.parse(SEASON_START)) / 864e5); }
function renderTimeline() {
  if (S.doc || S.state === 'loading') return;
  if (MOBILE && (S.sheet === 'full' || S.card)) return;
  const end = new Date(Date.parse(TODAY) + FORECAST_DAYS * 864e5).toISOString().slice(0, 10);
  const span = dayIndex(end);
  const pct = (iso) => (100 * dayIndex(iso)) / span;
  const passes = PASSES.passes.filter((p) => p.date <= TODAY);
  const empty = !S.scene;
  const ticks = empty ? '' : passes.map((p) => `<span class="tl-tick" style="left:${pct(p.date)}%" title="${esc(fechaCorta(p.date))}"></span>`).join('');
  let months = '';
  for (let y = 2025, m = 9; `${y}-${String(m + 1).padStart(2, '0')}-01` <= TODAY; m = (m + 1) % 12, y += m === 0 ? 1 : 0) {
    const iso = `${y}-${String(m + 1).padStart(2, '0')}-01`;
    // The last month label would collide with the forecast slot label.
    const show = (MOBILE ? m % 3 === 0 : true) && dayIndex(iso) < span - (MOBILE ? 60 : 35);
    if (show) months += `<span class="${m === 0 ? 'year' : ''}" style="left:${pct(iso)}%">${m === 0 ? y : MESES[m]}</span>`;
  }
  const cursorISO = SCENE.date;
  const cursor = empty ? '' : `<span class="tl-cursor" style="left:${pct(cursorISO)}%"></span>`;
  const tooltip = S.tooltip ? `<span class="tl-tooltip" style="left:${pct(cursorISO)}%">${esc(t('linea_tiempo.tick_tooltip', { fecha_larga: fechaLarga(cursorISO), estados: t('estado.observado') + ' (S2 L1C)' }))}</span>` : '';
  const dateBlock = empty
    ? `<div class="tl-date"><span class="d">${esc(t('linea_tiempo.sin_datos'))}</span><span class="small muted">${esc(t('linea_tiempo.sin_datos_detalle'))}</span></div>`
    : `<div class="tl-date"><span class="small muted">${esc(t('linea_tiempo.etiqueta'))}</span><span class="d num">${esc(fechaConDia(cursorISO))}</span>
        <div class="tl-btns"><button class="icon-btn" aria-label="${esc(t('linea_tiempo.anterior'))}">${icon('chevron-left')}</button><button class="icon-btn" aria-label="${esc(t('linea_tiempo.reproducir'))}">${icon('play')}</button><button class="icon-btn" aria-label="${esc(t('linea_tiempo.siguiente'))}">${icon('chevron-right')}</button></div></div>`;
  const legend = `<div class="tl-legend">${['observado', 'rellenado', 'modelado', 'prevision', 'pendiente'].map((e) => badge(e)).join('')}</div>`;
  const right = `<div class="tl-right"><div style="display:flex;gap:var(--space-1)"><button class="btn" ${empty ? 'disabled' : ''} title="${esc(t('linea_tiempo.tooltip_ultima'))}">${icon('arrow-right-to-line')}${esc(t('linea_tiempo.ultima'))}</button><button class="btn" aria-label="${esc(t('linea_tiempo.calendario'))}">${icon('calendar')}</button></div></div>`;
  const el = document.createElement('div');
  el.className = 'timeline';
  el.setAttribute('role', 'group');
  el.setAttribute('aria-label', t('linea_tiempo.etiqueta'));
  const track = empty ? '' : `
    <div class="tl-track" role="slider" tabindex="0" aria-label="${esc(t('linea_tiempo.etiqueta'))}" aria-valuetext="${esc(empty ? t('linea_tiempo.sin_datos') : fechaConDia(cursorISO))}" title="${esc(t('linea_tiempo.teclado'))}">
      <div class="tl-row obs">${ticks}</div>
      <div class="tl-row daily"><span class="seg pendiente" style="left:0;width:${pct(TODAY)}%" title="${esc(t('estado.tooltip_pendiente'))}"></span><span class="seg pendiente slot-prevision" style="left:${pct(TODAY)}%;right:0" title="${esc(t('linea_tiempo.tooltip_prevision_slot'))} ${esc(t('linea_tiempo.prevision_slot_pendiente'))}"></span></div>
      <div class="tl-months">${months}</div>
      <span class="tl-forecast-label" style="right:0">${esc(t('linea_tiempo.prevision_slot'))}</span>
      <span class="tl-today" style="left:${pct(TODAY)}%" title="${esc(t('linea_tiempo.hoy'))}"></span>${cursor}${tooltip}
    </div>`;
  if (empty) el.classList.add('empty');
  el.innerHTML = `${dateBlock}${track}${right}${MOBILE ? '' : `<div class="tl-legend-row">${legend}</div>`}`;
  if (S.state === 'error') return;
  $('#overlays').appendChild(el);
  const tip = el.querySelector('.tl-tooltip');
  if (tip) {
    // Keep the tooltip inside the viewport (it is centred on the cursor).
    const r = tip.getBoundingClientRect();
    if (r.left < 8) tip.style.transform = `translateX(calc(-50% + ${8 - r.left}px))`;
    if (r.right > innerWidth - 8) tip.style.transform = `translateX(calc(-50% - ${r.right - innerWidth + 8}px))`;
  }
}

/* ---------- overlays ---------- */
function renderOverlays(map) {
  const ov = $('#overlays');
  if (S.scene && !S.doc && S.section === 'nieve') {
    const chip = document.createElement('div');
    chip.className = 'legend-chip';
    chip.style.left = `calc(var(--layout-rail-width) + ${S.collapsed ? '0px' : 'var(--layout-panel-width)'} + var(--space-4))`;
    chip.style.top = 'var(--space-4)';
    chip.innerHTML = `${badge('observado')}<span class="num">${esc(t('leyenda.chip_mapa', { capa: t('capa.color_real.nombre') + ' S2 L1C', fecha_corta: fechaCorta(SCENE.date) }))}</span>`;
    ov.appendChild(chip);
  }
  if (SCREEN === 'nieve-info') {
    const anchor = document.querySelector('[data-info-anchor]').getBoundingClientRect();
    const pop = document.createElement('div');
    pop.className = 'popover';
    pop.setAttribute('role', 'dialog');
    pop.style.left = MOBILE ? '0' : `${anchor.right + 12}px`;
    pop.style.top = MOBILE ? 'var(--space-12)' : `${Math.max(16, anchor.top - 40)}px`;
    const items = PASSES.passes.find((p) => p.date === SCENE.date).items;
    pop.innerHTML = `<h3>${esc(t('capa.color_real.nombre'))}<button class="icon-btn" aria-label="${esc(t('info_capa.cerrar'))}">${icon('x')}</button></h3>
      <dl>
        <dt>${esc(t('info_capa.fuente'))}</dt><dd>Copernicus Sentinel-2 L1C (Earth Search, AWS)</dd>
        <dt>${esc(t('info_capa.resolucion'))}</dt><dd>${esc(t('capa.color_real.resolucion'))}</dd>
        <dt>${esc(t('info_capa.cadencia'))}</dt><dd>${esc(t('capa.color_real.cadencia'))}</dd>
        <dt>${esc(t('info_capa.fecha_dato'))}</dt><dd class="num">${esc(fechaCorta(SCENE.date))}</dd>
        <dt>${esc(t('info_capa.estado'))}</dt><dd>${badge('observado')}</dd>
        <dt>${esc(t('info_capa.escenas'))}</dt><dd class="num">${items.map((i) => esc(i).replace(/_/g, '_<wbr>')).join('<br>')}</dd>
      </dl>
      <p class="small muted" style="margin:var(--space-3) 0 0">${esc(t('capa.color_real.descripcion'))}</p>
      <a class="link" href="#">${esc(t('info_capa.metodo'))}</a>`;
    ov.appendChild(pop);
    if (!MOBILE) {
      const h = pop.getBoundingClientRect().height;
      pop.style.top = `${Math.max(16, Math.min(anchor.top - 40, innerHeight - h - 16))}px`;
    }
  }
  if (S.card) renderCard(map);
}

function renderCard(map) {
  const card = document.createElement('div');
  card.className = 'card';
  card.setAttribute('role', 'dialog');
  if (S.card === 'offline') {
    const cam = CAMS.find((c) => c.id === 'dgt-312');
    card.setAttribute('aria-label', camName(cam));
    card.innerHTML = `<div class="img off">${icon('camera-off', 32)}<div class="small" style="margin-top:var(--space-2)">${esc(t('webcam.offline_titulo'))}</div></div>
      <div class="body"><div class="row1"><span class="cname num">${esc(camName(cam))}</span><span class="status off">${icon('camera-off')}${esc(t('webcam.sin_imagen'))}</span></div>
      <p class="small muted" style="margin:var(--space-2) 0 0">${esc(t('webcam.offline_detalle'))}</p>
      <p class="small" style="margin:var(--space-2) 0 0">${esc(t('webcam.offline_ultima_desconocida'))}</p>
      <p class="small muted" style="margin:var(--space-1) 0 0">${esc(t('webcam.orientacion_pendiente'))}</p>
      <div class="credit">${esc(t('webcam.credito_dgt'))}</div></div>`;
    card.insertAdjacentHTML('afterbegin', '<div class="sheet-handle" aria-hidden="true"></div>');
    const pt = map.project([cam.longitude, cam.latitude]);
    card.style.left = `${pt.x + 40}px`;
    card.style.top = `${Math.max(16, pt.y - 140)}px`;
  } else {
    // Cetursa still saved with its HTTP Last-Modified (mockups/data/cetursa_pradollano.json); H4 credit line.
    // Age is measured against now (or ?now= for reproducible screenshots), so a later visit shows the real, older age.
    const rec = CETURSA;
    const cap = new Date(rec.http_last_modified);
    const now = q.get('now') ? new Date(q.get('now')) : new Date();
    const ageMs = Math.max(0, now - cap);
    const stale = ageMs > STALE_HOURS * 3600e3;
    const fmtHora = (d) => d.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Madrid' });
    const fmtDia = (d) => fechaCorta(new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Madrid' }).format(d));
    const status = stale
      ? `<span class="status" style="color:var(--color-warning)">${icon('clock')}${esc(t('webcam.antigua_corta'))}</span>`
      : `<span class="status live"><span class="cam-dot" aria-hidden="true"></span>${esc(t('webcam.en_directo'))}</span>`;
    card.setAttribute('aria-label', 'Pradollano');
    card.innerHTML = `<div class="sheet-handle" aria-hidden="true"></div><img class="img" alt="Pradollano, imagen de la cámara" src="data/${rec.file}">
      <div class="body"><div class="row1"><span class="cname">Pradollano</span>${status}</div>
      <p class="small num" style="margin:var(--space-2) 0 0">${esc(t('webcam.capturada', { fecha_corta: fmtDia(cap), hora: fmtHora(cap) }))} · ${esc(edad(ageMs, cap))}</p>
      ${stale ? `<p class="small" style="margin:var(--space-1) 0 0;color:var(--color-warning)">${esc(t('webcam.imagen_antigua', { horas: STALE_HOURS }))}</p>` : ''}
      <p class="small muted" style="margin:var(--space-1) 0 0">${esc(t('webcam.orientacion_pendiente'))}</p>
      <div class="row1" style="margin-top:var(--space-2)"><span class="credit" style="margin:0">${esc(t('webcam.credito_cetursa'))}</span><a class="small" href="#">${esc(t('webcam.abrir_fuente'))}</a></div></div>`;
    card.style.right = 'calc(var(--layout-map-control) + var(--space-8))';
    card.style.top = 'var(--space-4)';
  }
  $('#overlays').appendChild(card);
}

/* ---------- method page ---------- */
function renderDoc() {
  const d = document.createElement('main');
  d.className = 'doc';
  const sec = (k) => esc(t('metodo.' + k));
  d.innerHTML = `<div class="doc-inner">
    <nav aria-label="${esc(t('metodo.indice'))}"><div class="eyebrow" style="margin-bottom:var(--space-2)">${esc(t('metodo.indice'))}</div>
      ${['seccion_nieve_observada', 'seccion_nieve_diaria', 'seccion_modelo', 'seccion_color_real', 'seccion_webcams', 'seccion_validacion', 'seccion_limites', 'seccion_datos'].map((k, i) => `<a href="#" class="${i === 0 ? 'active' : ''}">${sec(k)}</a>`).join('')}
      <button class="btn" style="margin-top:var(--space-4)">${icon('arrow-left')}${esc(t('metodo.volver_mapa'))}</button></nav>
    <article>
      <div class="eyebrow">${esc(t('panel.metodo.eyebrow'))}</div>
      <h1>${esc(t('panel.metodo.titulo'))}</h1>
      <p class="muted">${esc(t('panel.metodo.subtitulo'))}</p>
      <h2>${sec('seccion_nieve_observada')}</h2>
      <div class="facts small"><div><div class="muted caption">${esc(t('info_capa.fuente'))}</div>${esc(t('metodo.fuente_nieve_observada'))}</div><div><div class="muted caption">${esc(t('info_capa.resolucion'))}</div>20 m</div><div><div class="muted caption">${esc(t('info_capa.cadencia'))}</div>${esc(t('capa.nieve_observada.cadencia'))}</div></div>
      <h3>${sec('como_se_calcula')}</h3>
      <p>${sec('nieve_observada_calculo_1')}</p>
      <p>${sec('nieve_observada_calculo_2')}</p>
      <h3>${sec('como_se_valida')}</h3>
      <p>${sec('nieve_observada_validacion')}</p>
      <div class="pend">${esc(t('metodo.resultado_pendiente'))}</div>
      <h2>${sec('seccion_limites')}</h2>
      <ul><li>${esc(t('metodo.limite_sombra'))}</li><li>${esc(t('metodo.limite_bosque'))}</li><li>${esc(t('metodo.limite_estacion'))}</li></ul>
    </article></div>`;
  $('#app').appendChild(d);
  $('#panel').style.display = 'none';
  $('#collapse').style.display = 'none';
}

/* ---------- timeline state specimen ---------- */
// Spec sheet for T4.2: each tick and strip state drawn with the component's own classes. No dates, no data.
function renderTimelineStates() {
  const d = document.createElement('main');
  d.className = 'doc';
  const row = (estado, glyph) => `<div class="spec-row"><div>${badge(estado)}</div><div class="spec-glyph">${glyph}</div><div class="small">${esc(t('estado.tooltip_' + estado))}</div></div>`;
  // Schematic strip in abstract day units: 0..30 past, 30 = today, 30..36 forecast slot.
  const u = (x) => (100 * x) / 36;
  const seg = (cls, a, b) => `<span class="seg ${cls}" style="left:${u(a)}%;width:${u(b - a)}%"></span>`;
  const ticks = [2, 5, 9, 14, 21, 26].map((x) => `<span class="tl-tick" style="left:${u(x)}%"></span>`).join('');
  d.innerHTML = `<div class="doc-inner" style="grid-template-columns:1fr"><article>
    <div class="eyebrow">${esc(t('linea_tiempo.etiqueta'))}</div>
    <h1>${esc(t('linea_tiempo.leyenda_observado'))}, ${esc(t('linea_tiempo.leyenda_rellenado')).toLowerCase()}, ${esc(t('linea_tiempo.leyenda_modelado')).toLowerCase()} y ${esc(t('linea_tiempo.leyenda_prevision')).toLowerCase()}</h1>
    ${row('observado', '<span class="tl-tick"></span>')}
    ${row('rellenado', '<span class="seg rellenado"></span>')}
    ${row('modelado', '<span class="seg modelado"></span>')}
    ${row('prevision', '<span class="seg prevision"></span>')}
    ${row('pendiente', '<span class="seg pendiente"></span>')}
    <div class="spec-strip" aria-hidden="true">
      <div class="tl-row obs">${ticks}</div>
      <div class="tl-row daily">${seg('rellenado', 0, 12)}${seg('modelado', 12, 30)}${seg('prevision', 30, 33)}${seg('pendiente slot-prevision', 33, 36)}</div>
      <span class="tl-today" style="left:${u(30)}%"></span>
      <span class="cap" style="left:${u(6)}%">${esc(t('estado.rellenado'))}</span>
      <span class="cap" style="left:${u(21)}%">${esc(t('estado.modelado'))}</span>
      <span class="cap" style="left:${u(30)}%">${esc(t('linea_tiempo.hoy'))}</span>
      <span class="cap" style="left:${u(33)}%">${esc(t('linea_tiempo.prevision_slot'))}</span>
    </div>
  </article></div>`;
  $('#app').appendChild(d);
  $('#panel').style.display = 'none';
  $('#collapse').style.display = 'none';
}

/* ---------- map ---------- */
function initMap() {
  const halo = tok('--color-map-halo');
  const ink = tok('--color-ink');
  const accent = tok('--color-accent');
  const sources = {
    ign: {
      type: 'raster', tileSize: 256, maxzoom: 17,
      tiles: ['https://www.ign.es/wmts/ign-base?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=IGNBase-gris&STYLE=default&TILEMATRIXSET=GoogleMapsCompatible&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=image/jpeg'],
    },
    basins: { type: 'geojson', data: BASINS },
  };
  const layers = [{ id: 'ign', type: 'raster', source: 'ign' }];
  if (S.scene) {
    sources.l1c = { type: 'image', url: SCENE.img, coordinates: SCENE.corners };
    layers.push({ id: 'l1c', type: 'raster', source: 'l1c', paint: { 'raster-fade-duration': 0 } });
  }
  layers.push(
    { id: 'basin-halo', type: 'line', source: 'basins', paint: { 'line-color': halo, 'line-width': 3.5, 'line-opacity': 0.9 } },
    { id: 'basin-line', type: 'line', source: 'basins', paint: { 'line-color': ink, 'line-width': 1.25 } },
  );
  if (S.basin) {
    layers.push(
      { id: 'basin-sel-halo', type: 'line', source: 'basins', filter: ['==', ['get', 'nom_rio_1'], S.basin], paint: { 'line-color': halo, 'line-width': 6 } },
      { id: 'basin-sel', type: 'line', source: 'basins', filter: ['==', ['get', 'nom_rio_1'], S.basin], paint: { 'line-color': accent, 'line-width': 3 } },
    );
  }
  const map = new maplibregl.Map({
    container: 'map',
    style: { version: 8, sources, layers },
    bounds: [[-3.56, 36.97], [-3.16, 37.18]],
    fitBoundsOptions: { padding: MOBILE ? { top: 70, bottom: 260, left: 10, right: 10 } : { top: 40, bottom: 120, left: (S.collapsed ? 64 : 384) + 20, right: 70 } },
    attributionControl: false,
    fadeDuration: 0,
  });
  // Webcam symbols: DGT cams from the real catalogue, all offline today; no bearing yet so no cone.
  CAMS.forEach((c) => {
    const el = document.createElement('div');
    el.setAttribute('role', 'button');
    el.setAttribute('aria-label', t('webcam.tooltip_simbolo', { nombre: c.name, estado: c.offline ? t('webcam.sin_imagen') : t('webcam.en_directo') }));
    el.style.cssText = `width:24px;height:24px;border-radius:var(--radius-full);background:var(--color-panel);border:1.5px solid var(--color-text-muted);display:grid;place-items:center;color:var(--color-text-muted);box-shadow:var(--shadow-float)`;
    if (S.card === 'offline' && c.id === 'dgt-312') el.style.cssText += ';outline:2px solid var(--color-accent);outline-offset:2px';
    el.innerHTML = icon('camera-off', 14);
    new maplibregl.Marker({ element: el }).setLngLat([c.longitude, c.latitude]).addTo(map);
  });
  const attr = [t('mapa.atribucion_ign')];
  if (S.scene) attr.unshift(t('mapa.atribucion_s2', { anio: '2026' }));
  $('#attribution').innerHTML = `<span class="attr-icon" title="${esc(attr.join(' · '))}" aria-label="${esc(attr.join(' · '))}">${icon('info', 20)}</span><span class="attr-text">${esc(attr.join(' · '))}</span>`;
  return map;
}

async function main() {
  const load = (p) => fetch(p).then((r) => { if (!r.ok) throw new Error(p); return r.json(); });
  [T, R, C, BASINS, CAMS, PASSES, FLOW_GUADALFEO, CETURSA] = await Promise.all([
    load('../tokens.json'), load('../ramps.json'), load('../copy.es.json'),
    load(REPO + 'data/basins.geojson'), load(REPO + 'frontend/public/data/webcams.json'),
    load('data/s2_passes.json'), load(REPO + 'data/flow/guadalfeo.json'), load('data/cetursa_pradollano.json'),
  ]);
  applyTokens(T);
  fillCopy();
  if (S.specimen) renderTimelineStates(); else if (S.doc) renderDoc(); else renderPanel();
  renderTimeline();
  const map = initMap();
  drawIcons();
  hydrateLegends();
  map.once('idle', () => {
    renderOverlays(map);
    drawIcons();
    document.body.dataset.ready = '1';
  });
}
main().catch((e) => { document.body.dataset.ready = 'error'; document.body.insertAdjacentHTML('beforeend', `<pre>${esc(e.stack)}</pre>`); });
