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

## Artículos de referencia

Los artículos y repos de inspiración para el diseño del modelo están listados en [`development_strategy.md`](../development_strategy.md).
