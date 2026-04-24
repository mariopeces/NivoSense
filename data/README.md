# Data

Geometrías estáticas que consume el backend y el frontend. Los ficheros de esta carpeta se suben al bucket `gs://nivosense-cogs/static/` durante el deploy (o se sirven embebidos desde el frontend).

Sistema de coordenadas: **EPSG:4326** (lat/lon).

## `basins.geojson`

Cuencas hidrográficas de la región de interés.

Esquema esperado por feature:

```json
{
  "type": "Feature",
  "geometry": { "type": "Polygon", "coordinates": [...] },
  "properties": {
    "id": "genil",
    "name": "Cuenca del Genil",
    "area_km2": 312.5
  }
}
```

`geometry` puede ser `Polygon` o `MultiPolygon`.

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
