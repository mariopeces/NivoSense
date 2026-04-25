# ML

Entrenamiento e inferencia del modelo de predicción de NDSI. Esta carpeta vive fuera del pipeline de deploy: el modelo se entrena offline y la única salida que consume la app son los COGs subidos a GCS.

## Contrato de salida

Por cada horizonte de predicción, el modelo produce un COG y lo sube a:

```
gs://nivosense-cogs/predictions/sierra-nevada/ndsi_{horizon}.tif
```

Horizontes soportados por el backend (ver `backend/layers.yaml`):

| Horizonte | `{horizon}` |
|---|---|
| Cobertura actual (nowcast) | `nowcast` |
| +24 horas | `plus24h` |
| +48 horas | `plus48h` |
| +72 horas | `plus72h` |
| +7 días | `plus7d` |
| +1 mes | `plus1m` |
| +2 meses | `plus2m` |

Cada corrida **sobreescribe** el fichero correspondiente (no hay versionado). Si el modelo está listo antes que el endpoint de tiles, se puede subir primero un COG histórico a `ndsi_nowcast.tif` para desbloquear a frontend y backend.

## Formato del COG

- **Tipo:** single-band raster.
- **Dtype:** `float32`, valores de NDSI en `[0, 1]`. `nodata` en píxeles sin predicción válida.
- **CRS:** `EPSG:3857` (Web Mercator). Si el modelo trabaja nativo en `EPSG:4326` reproyectar antes de subir.
- **Overviews:** internos, factores `[2, 4, 8, 16]`.
- **Compresión:** `DEFLATE` (o `LZW`).
- **Perfil COG:** validado con `rio cogeo validate`.

Ejemplo de creación con `rio-cogeo`:

```bash
rio cogeo create input.tif ndsi_plus24h.tif \
  --cog-profile deflate \
  --overview-level 4 \
  --web-optimized
```

Subida:

```bash
gsutil cp ndsi_plus24h.tif gs://nivosense-cogs/predictions/sierra-nevada/
```

## Añadir un horizonte nuevo

1. Joan genera y sube el COG siguiendo el formato y convención de nombres.
2. Mario añade la entrada en `backend/layers.yaml`.
3. El frontend recoge la capa automáticamente vía `GET /layers`.

## River flow ingest

El feature **Water by River → River flow** se alimenta de JSONs precomputados en
`gs://nivosense-cogs/static/sierra-nevada/flow/{river_id}.json`. Los datos crudos
vienen de descargas manuales del SAIH Guadalquivir (Atlántico, lado norte de
Sierra Nevada) y de Hidrosur (Cuencas Mediterráneas Andaluzas, lado sur). Ningún
servicio externo se llama en runtime — todo se sirve desde el bucket público.

### Ríos soportados

| `river_id` | Río | Cuenca | Estación | Fuente | Variable |
|---|---|---|---|---|---|
| `dilar` | Río Dilar | Guadalquivir | 5086 (Dilar, A05) | SAIH Guadalquivir | `A05_211_X` — caudal m³/s |
| `alhori` | Río Alhorí | Guadalquivir | 5051 (Jerez del Marquesado, A53) | SAIH Guadalquivir | `A53_211_X` — caudal m³/s |
| `guadalfeo` | Río Guadalfeo | Guadalfeo o Cadiar | 73 (Órgiva) | Hidrosur | caudal m³/s |
| `andarax` | Río Andarax | Andarax | 90 (Terque, Río Nacimiento) | Hidrosur | caudal m³/s |

### Workflow de descarga (manual, una sola vez por estación)

#### SAIH Guadalquivir — Dilar y Jerez del Marquesado

1. Abrir [https://www.chguadalquivir.es/saih/DatosHistoricos.aspx](https://www.chguadalquivir.es/saih/DatosHistoricos.aspx).
2. **Fecha inicial / final:** rango ≤ 170 días para datos diarios (límite del portal).
3. **Tipo de periodo:** Diario.
4. **Formato:** Excel.
5. **Punto de control:**
   - Para Dilar: `A05_DILAR (5086)`.
   - Para Jerez del Marquesado: `A53_JEREZ_DEL_MARQUESADO (5051)`.
6. **Tipo de dato:**
   - Dilar: `A05_211_X — CAUDAL RIO DILAR (m3/s)`.
   - Jerez del Marquesado: `A53_211_X — CAUDAL RIO ALHORI (m3/s)`.
7. **Agregar Señal** → **Visualizar** → **Descargar Excel**.
8. Para más de 170 días, repetir con rangos sucesivos. El script `normalize_flow.py`
   acepta múltiples ficheros y los concatena.

Guardar los Excel en `data/flow/raw/dilar_<YYYYMMDD>_<YYYYMMDD>.xlsx` y
`data/flow/raw/alhori_*.xlsx`.

#### Hidrosur — Guadalfeo y Andarax

1. Abrir [https://www.redhidrosurmedioambiente.es/saih/listado/estaciones](https://www.redhidrosurmedioambiente.es/saih/listado/estaciones)
   → "Datos a la carta".
2. Seleccionar estación: **73** (RÍO GUADALFEO ÓRGIVA) o **90** (RÍO NACIMIENTO TERQUE).
3. Variable: caudal. Periodo: diario. Rango: año hidrológico (oct 2024 – sep 2025).
4. Exportar CSV/Excel y guardar en `data/flow/raw/guadalfeo_*.xlsx` o
   `data/flow/raw/andarax_*.xlsx`.

> Si la estación 73 (Órgiva) no reporta caudal — solo nivel/pluviometría — busca
> una estación equivalente aguas abajo del Guadalfeo y actualiza la entrada
> correspondiente en `backend/main.py::RIVERS`.

### Normalización a JSON canonical

```bash
python ml/normalize_flow.py data/flow/raw/dilar_*.xlsx data/flow/dilar.json \
  --station-id 5086 \
  --station-name "Río Dilar — Dilar" \
  --source "SAIH Guadalquivir" \
  --license "© Confederación Hidrográfica del Guadalquivir"
```

El script auto-detecta las columnas de fecha (`Fecha`, `Date`, etc.) y de
caudal (cualquier columna con `caudal`, `m3/s`, o terminada en `_X`).
Acepta múltiples inputs y los deduplica/ordena por fecha.

Repetir para los 4 ríos:

```bash
python ml/normalize_flow.py data/flow/raw/alhori_*.xlsx data/flow/alhori.json \
  --station-id 5051 \
  --station-name "Jerez del Marquesado (A53)" \
  --source "SAIH Guadalquivir"

python ml/normalize_flow.py data/flow/raw/guadalfeo_*.xlsx data/flow/guadalfeo.json \
  --station-id 73 \
  --station-name "Órgiva" \
  --source "Hidrosur"

python ml/normalize_flow.py data/flow/raw/andarax_*.xlsx data/flow/andarax.json \
  --station-id 90 \
  --station-name "Terque (Río Nacimiento)" \
  --source "Hidrosur"
```

### Subida al bucket

```bash
gcloud storage cp data/flow/dilar.json     gs://nivosense-cogs/static/sierra-nevada/flow/dilar.json
gcloud storage cp data/flow/alhori.json    gs://nivosense-cogs/static/sierra-nevada/flow/alhori.json
gcloud storage cp data/flow/guadalfeo.json gs://nivosense-cogs/static/sierra-nevada/flow/guadalfeo.json
gcloud storage cp data/flow/andarax.json   gs://nivosense-cogs/static/sierra-nevada/flow/andarax.json
```

Tras la subida, el endpoint `GET /rivers/{river_id}/flow` devuelve el JSON al
frontend y se renderiza en `RiverFlowChart`.

### Esquema del JSON

```json
{
  "station_id": "5086",
  "station_name": "Río Dilar — Dilar",
  "variable": "caudal",
  "unit": "m3/s",
  "source": "SAIH Guadalquivir",
  "license": "© Confederación Hidrográfica del Guadalquivir",
  "first_date": "2024-10-01",
  "last_date": "2026-04-25",
  "points": [
    { "date": "2024-10-01", "label": "01 Oct", "value": 0.42 }
  ]
}
```

## Artículos de referencia

Los artículos y repos de inspiración para el diseño del modelo están listados en [`development_strategy.md`](../development_strategy.md).
