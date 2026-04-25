# Arquitectura

Documento vivo. Lo actualizamos a medida que las decisiones se consolidan durante el hackathon.

## Visión general

```
    Joan (modelo ML)              Guille / Mario (infra + app)
    ─────────────────             ─────────────────────────────

    entrena offline
          │
          ▼
    genera COGs NDSI ─────►  GCS: nivosense-cogs/predictions/...
                                         │
                                         ▼
                               FastAPI + rio-tiler  (Cloud Run)
                                         │
                                  ┌──────┴──────┐
                                  │             │
                                  ▼             ▼
                            /tiles/{layer}   /basins/{id}/stats
                            /layers          /routes/{id}/overlay
                                  │             │
                                  └──────┬──────┘
                                         ▼
                              Frontend React + MapLibre
                              (servido desde GCS estático)
```

Flujo resumido: Joan sube COGs a un bucket conocido; el backend los lee con `rio-tiler` y los expone como tiles XYZ y estadísticas agregadas; el frontend los pinta sobre MapLibre y dibuja las interacciones (rutas, cuencas, gráficas).

## Decisiones de stack

### Backend: FastAPI + rio-tiler

- FastAPI porque el ecosistema geoespacial en Python es el que nos da más velocidad (`rio-tiler`, `rasterio`, `geopandas`, `shapely`).
- `rio-tiler` lee COGs directamente desde GCS con HTTP range requests (a través de GDAL `/vsigs/`). No necesitamos pre-generar tiles ni mantener un caché.
- Un solo fichero `main.py` al principio. Si crece, lo partimos durante el fin de semana.

### Frontend: React + Vite + MapLibre GL JS + Tailwind

- React porque el panel lateral tiene suficiente estado interactivo (selectores, paneles, gráficas) como para que merezca un modelo de componentes.
- Vite para HMR rápido y arranque sin configuración.
- MapLibre GL JS para el mapa (open source, soporta raster tiles directo, vector tiles, y controles de dibujo via `mapbox-gl-draw`).
- Tailwind + [shadcn/ui](https://ui.shadcn.com) para no perder tiempo en CSS.
- Recharts para las gráficas de tendencia.

### Infra: Cloud Run + GCS + Artifact Registry

- **Cloud Run** porque escala a 0 (no pagamos mientras nadie usa la demo) y el contenedor de la API se despliega en segundos.
- **GCS** como almacén único: COGs de predicción, GeoJSONs estáticos (cuencas, rutas) y frontend empaquetado.
- **Artifact Registry** para la imagen Docker de la API.
- **Cloud Build** para CI: un trigger por push a `main` que hace build + deploy de la API.
- Región: `europe-west1` (cerca de los datos Copernicus y de los usuarios del demo).

### Cosas que quedan fuera (y por qué)

- **Auth.** La demo es pública; no hay usuarios, no hay tenants. Si el jurado pregunta, respondemos que está fuera de scope.
- **Base de datos relacional.** Las cuencas y rutas son GeoJSONs estáticos servidos desde el mismo bucket. No merece montar PostGIS para esto.
- **Multi-entorno (dev/prd).** Un único proyecto GCP (`nivosense`). Un entorno es suficiente para el demo.
- **Caché de tiles.** `rio-tiler` sobre COG bien optimizado es rápido. Si fuera lento, optimizaríamos el COG antes que cachear.
- **IaC (Terraform).** Guille crea los recursos con `gcloud` y documenta los comandos. Para el scope del finde no compensa.

## Estructura del repo

```
NivoSense/
├── backend/              FastAPI + Dockerfile
│   ├── main.py
│   ├── layers.yaml       manifiesto de capas NDSI disponibles
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/             React + Vite
│   ├── src/
│   ├── index.html
│   └── package.json
├── data/                 geometrías estáticas (se suben a GCS)
│   ├── basins.geojson    cuencas hidrográficas de Sierra Nevada
│   └── routes.geojson    ski touring + snowshoe
├── ml/                   entrenamiento (Joan) — no entra en deploy
├── deploy/
│   ├── cloudbuild.yaml   build + deploy API
│   ├── deploy-web.sh     sync frontend a GCS
│   └── SETUP.md          comandos gcloud para crear los recursos
├── ARCHITECTURE.md
├── ROADMAP.md
├── README.md
└── development_strategy.md
```

## Contrato de API

Endpoints que expone el backend (borrador, puede ajustarse durante el fin de semana):

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/health` | Liveness check. |
| `GET` | `/layers` | Lista las capas NDSI disponibles (nowcast, +24h, +48h, +72h, +7d…). |
| `GET` | `/tiles/{layer}/{z}/{x}/{y}.png` | Tile PNG renderizado desde el COG de la capa. |
| `GET` | `/basins` | Lista de cuencas hidrográficas (id + nombre). |
| `GET` | `/basins/{id}` | Geometría de la cuenca (GeoJSON). |
| `GET` | `/basins/{id}/stats?layer={layer}` | `{ snow_pct, no_snow_pct, area_km2, trend: [...] }` |
| `GET` | `/routes` | Lista de rutas (id, nombre, tipo: ski_touring \| snowshoe). |
| `GET` | `/routes/{id}` | Geometría de la ruta. |
| `GET` | `/routes/{id}/overlay?layer={layer}` | Geometría de la ruta segmentada en tramos con/sin nieve + porcentajes. |
| `GET` | `/rivers` | Lista de ríos con estación de aforo (id, name, basin_cod_uni, station_id, source). |
| `GET` | `/rivers/{id}/flow` | Serie temporal de caudal (m³/s) precomputada en `gs://nivosense-cogs/static/sierra-nevada/flow/{id}.json`. |

Formato de respuesta: JSON (excepto tiles). CORS abierto durante el hackathon.

## Contrato ML ↔ Backend

Joan produce un COG por cada horizonte de predicción y lo sube al bucket:

```
gs://nivosense-cogs/predictions/sierra-nevada/ndsi_{horizon}.tif
```

Donde `{horizon}` es uno de: `nowcast`, `plus24h`, `plus48h`, `plus72h`, `plus7d`, `plus1m`, `plus2m`.

Joan sobreescribe el fichero en cada corrida (sin versionado). El backend lee un `layers.yaml` que mapea `horizon → ruta GCS`, así que añadir un horizonte es editar un yaml, no tocar código.

**Formato del COG:**
- Raster single-band, `float32`, valores de NDSI en `[0, 1]` (o `nodata` en píxeles sin dato).
- Reproyectado a `EPSG:3857` (Web Mercator) para evitar reproyección en tiempo de tile.
- Overviews internos (`gdaladdo`) para que `rio-tiler` sirva niveles de zoom bajos eficientemente.
- Compresión `DEFLATE` o `LZW`.

## Plan de deploy

1. **Recursos GCP** (Guille crea con `gcloud`, documenta en `deploy/SETUP.md`):
   - Proyecto: `nivosense`.
   - Bucket `nivosense-cogs` (lectura pública) para COGs y GeoJSONs estáticos.
   - Bucket `nivosense-web` (lectura pública) para el frontend empaquetado.
   - Artifact Registry `nivosense-docker` en `europe-west1`.
   - Service account `nivosense-api@nivosense.iam.gserviceaccount.com` con `roles/storage.objectViewer` en el bucket de COGs.
   - Cloud Run service `nivosense-api` en `europe-west1`.
   - Trigger de Cloud Build en push a `main` con filtro `backend/**`.

2. **Pipeline API** (`deploy/cloudbuild.yaml`):
   - Build de la imagen Docker desde `backend/Dockerfile`.
   - Push a Artifact Registry.
   - Deploy a Cloud Run (`--allow-unauthenticated`).

3. **Pipeline frontend** (`deploy/deploy-web.sh`, ejecutado manualmente):
   - `npm run build` en `frontend/`.
   - Inyecta la URL de la API de Cloud Run en el build.
   - `gsutil -m rsync` del `dist/` al bucket `nivosense-web`.

4. **CORS del bucket** de COGs: configurado vía `gsutil cors set` para permitir `GET` desde cualquier origen (solo durante el hackathon).
