# Roadmap del fin de semana

Timeline orientativo. Las horas son flexibles; los hitos no.

## Reparto

| Persona | Responsabilidad |
|---|---|
| Mario | Backend (FastAPI), frontend (React), integración, product. |
| Joan | Modelo ML + generación de COGs de predicción. |
| Guille | Infra GCP + pipeline de deploy + soporte a Mario en lo que haga falta. |

## Sábado

### Mañana (08:00 – 13:00)

- **Guille:** crea proyecto `nivosense` en GCP, habilita APIs, crea buckets (`nivosense-cogs`, `nivosense-web`), Artifact Registry, service account. Documenta los comandos en `deploy/SETUP.md`.
- **Mario:** scaffolding del repo. `backend/main.py` con `/health`, Dockerfile mínimo, `requirements.txt`. `frontend/` con `npm create vite@latest`, MapLibre instalado, mapa base centrado en Sierra Nevada.
- **Joan:** preparación de datos de entrenamiento. Primer COG de NDSI histórico subido al bucket como "capa nowcast" para desbloquear a Mario (aunque aún no haya predicción).

**Hito:** a las 13:00 existe un Cloud Run desplegado que responde `/health` y un frontend local que muestra un mapa de Sierra Nevada con la capa NDSI histórica encima.

### Tarde (14:00 – 20:00)

- **Guille:** pipeline `cloudbuild.yaml` funcionando con trigger en `main`. Script `deploy-web.sh` que sube el frontend al bucket.
- **Mario:** endpoint `/tiles/{layer}/{z}/{x}/{y}.png` con `rio-tiler`. Selector de capas en el panel lateral. Endpoint `/layers` leyendo `layers.yaml`. Carga de `basins.geojson` y `routes.geojson` en el frontend (como overlays seleccionables).
- **Joan:** primer modelo entrenado. Primer COG de predicción `+24h` subido al bucket.

**Hito:** a las 20:00 el frontend permite cambiar entre nowcast y +24h y ver la diferencia.

## Domingo

### Mañana (08:00 – 13:00)

- **Mario:** endpoint `/basins/{id}/stats` con cálculo de porcentaje de cobertura (zonal stats sobre el COG). Panel "Stats" del sidebar: selector de cuenca, dibujo de la cuenca en el mapa, gráfica de tendencia con Recharts. Endpoint `/routes/{id}/overlay` con intersección ruta × COG.
- **Joan:** COGs restantes (+48h, +72h, +7d). Si le da tiempo, +1m y +2m.
- **Guille:** apoyo a Mario. Configuración de CORS del bucket. Revisión de que todo el pipeline está verde.

**Hito:** a las 13:00 están todos los endpoints funcionando y todas las capas de predicción disponibles.

### Tarde (14:00 – 18:00)

- **Mario:** pulido UI (loading states, simbología, responsive), créditos a Darwin Geospatial en footer con logo + enlace, texto del panel, favicon, estados vacíos.
- **Todos:** prueba end-to-end del demo. Grabación de vídeo de respaldo por si la red del evento va mal.

**Hito:** a las 18:00 la demo está desplegada, probada y con vídeo de backup.

## Guión de la demo

1. Abrir la app. Mapa de Sierra Nevada con cobertura de nieve actual.
2. Cambiar de capa: nowcast → +24h → +72h. Explicar la predicción.
3. Abrir el panel de stats, seleccionar cuenca del Genil. Mostrar % cobertura y gráfica.
4. Abrir el panel de rutas, elegir una ruta clásica de ski touring. Cruzarla con la capa +72h. Mostrar tramos con/sin nieve.
5. Cerrar con los créditos y el equipo.

## Criterios de recorte

Si vamos tarde, recortamos en este orden:

1. Predicciones +1m y +2m (las deja Joan fuera si no están sólidas).
2. Gráfica de tendencia histórica (se muestra solo el valor actual).
3. Panel de rutas (si no llega el overlay ruta × nieve, se muestran solo dibujadas).
4. Cuencas individuales (mostrar solo el % global de Sierra Nevada).

El core innegociable es: mapa + capas de predicción NDSI + demo desplegado en Cloud Run.
