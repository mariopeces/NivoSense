# Data

Geometrías estáticas que consume el backend y el frontend. Los ficheros de esta carpeta se suben al bucket `gs://nivosense-cogs/static/` durante el deploy (o se sirven embebidos desde el frontend).

Sistema de coordenadas: **EPSG:4326** (lat/lon).

## `domain.geojson` and `basins.geojson`

Built by `python -m pipelines.domain.build` (never edited by hand), which also writes the byte-identical copies in `frontend/public/data/` and the `bbox` of `regions/sierra-nevada.json`. Source URLs, licences and retrieval dates are in each file's `metadata.sources`; areas are planar km2 in EPSG:25830.

`domain.geojson` holds three features (`part`): `domain` (Espacio Natural Sierra Nevada, the union of the two parks), `national_park` (MITECO ENP 2025) and `natural_park` (REDIAM RENPA; per Decreto 238/2011 it is the peripheral protection zone of the National Park).

`basins.geojson` holds the outermost rivers of MITECO "Subcuencas de ríos completos clasificadas según Pfafstetter modificado" that touch the domain, clipped to it:

```json
{
  "type": "Feature",
  "geometry": { "type": "MultiPolygon", "coordinates": [...] },
  "properties": {
    "COD_MAR": "M",
    "cod_uni": 604456,
    "pfafrio": "200134",
    "nom_rio_1": "RIO GUADALFEO O RIO CADIAR",
    "Cuen_Tipo": null,
    "source_area_km2": 1302.072,
    "domain_area_km2": 492.346
  }
}
```

`source_area_km2` is the whole sub-basin as published by MITECO; `domain_area_km2` is the part inside the domain. `sources/` keeps the clipped MITECO sub-basin copy the build reads (Fuente: Ministerio para la Transición Ecológica y el Reto Demográfico).

## `routes.geojson`

Rutas clásicas de ski touring y snowshoe en la región.

Esquema esperado por feature:

```json
{
  "type": "Feature",
  "geometry": { "type": "LineString", "coordinates": [...] },
  "properties": {
    "id": "veleta-clasica",
    "name": "Veleta clásica",
    "type": "ski_touring",
    "distance_km": 12.4,
    "elevation_gain_m": 1100
  }
}
```

`properties.type`: `ski_touring` o `snowshoe`.
