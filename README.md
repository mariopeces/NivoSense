# NivoSense

Visor en tiempo real de cobertura de nieve para zonas montañosas, con predicción a corto y medio plazo.

Proyecto desarrollado para el **Cassini Hackathon** (abril 2026). Región inicial: Sierra Nevada (España).

## Qué hace

- Muestra la cobertura de nieve actual (NDSI derivado de Sentinel-2).
- Predice cobertura a +24h, +48h, +72h, +7 días (y si el modelo acompaña, +1 y +2 meses).
- Calcula el porcentaje de nieve por cuenca hidrográfica y su tendencia.
- Cruza rutas clásicas de ski touring y raquetas con la capa de nieve elegida para saber qué tramos están cubiertos.

## Stack

- **Frontend:** React + Vite + MapLibre GL JS + Tailwind.
- **Backend:** FastAPI + rio-tiler (Python 3.11, en Docker).
- **ML:** modelo de predicción de NDSI entrenado offline; salida en formato COG.
- **Infra:** Google Cloud (Cloud Run + GCS + Artifact Registry + Cloud Build), región `europe-west1`.

Detalle técnico completo en [ARCHITECTURE.md](ARCHITECTURE.md). Plan del fin de semana en [ROADMAP.md](ROADMAP.md). Briefing original del proyecto en [development_strategy.md](development_strategy.md).

## Equipo

- **Mario** — producto, frontend, backend.
- **Joan** — modelo ML.
- **Guille** — infraestructura GCP.

## Estado

Work in progress durante el fin de semana del hackathon. El repo se construye en directo; consulta el historial de commits para seguir el progreso.

## Créditos

Proyecto impulsado con el apoyo de [Darwin Geospatial](https://darwingeospatial.com).
