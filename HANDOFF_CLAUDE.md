# Handoff para Claude Code

## Objetivo

Dejar NivoSense operativo como aplicación pública para Sierra Nevada, con el frontend en GitHub Pages y procesos programados en GitHub Actions. La aplicación debe mostrar únicamente datos reales y declarar de forma visible cualquier capa que todavía no esté disponible.

Horizontes meteorológicos únicos: `+24 h`, `+48 h`, `+72 h` y `+120 h`.

Lee `AGENTS.md` completo antes de modificar nada. Mantén el código recién escrito dentro de este repositorio, evita datos inventados y no añadas compatibilidad retrospectiva ni abstracciones preventivas.

## Estado de Git

La rama activa es `main`. Está limpia y siete commits por delante de `origin/main`:

```text
b229ea5 Serve GFSC observations from static hosting
9fd2bc6 Upgrade MapLibre past XSS advisory
4e1b72e Deploy frontend with GitHub Pages
3f8a21c Align forecast horizons to five days
4d78056 Add DGT webcam catalog and map layer
34fffb8 Add scheduled GFS forecast pipeline
7323643 Add scheduled GFSC observation pipeline
```

No se ha hecho `push`.

Hay tres worktrees de agentes:

```text
C:\Users\mario\Documents\GitHub\NivoSense-worktrees\snow-observations
C:\Users\mario\Documents\GitHub\NivoSense-worktrees\weather-forecasts
C:\Users\mario\Documents\GitHub\NivoSense-worktrees\webcams-map
```

## Trabajo ya integrado

### Cobertura de nieve

- Descubrimiento y descarga de GFSC mediante credenciales CDSE.
- Conservación del GeoTIFF científico como artifact de Actions.
- Generación de `snow_cover.png` georreferenciado para alojamiento estático.
- Manifiesto con procedencia, fecha, antigüedad, calidad, bbox y capa web.
- La web intenta cargar la observación estática y conserva el backend como fallback.
- Nueve pruebas offline del pipeline.

Commit integrado: `b229ea5`.

### Forecast meteorológico

- Pipeline inicial GFS en `pipelines/weather_forecasts/`.
- Manifiesto y GeoTIFF para los cuatro horizontes.
- Workflow programado.

El pipeline integrado en `main` todavía tiene un error: suma productos APCP de 3 y 6 horas que se solapan. No debe publicarse así.

La corrección y la integración web están listas en el commit pendiente `15e2fd9` de `feature/weather-forecasts`.

### Webcams

- Parser del feed DATEX II oficial de DGT.
- Ocho cámaras reales de la A-395 dentro del bbox.
- Catálogo estático, marcadores MapLibre y panel lateral.
- Actualización horaria mediante Actions.

Commit integrado: `4d78056`.

Una mejora del workflow Pages y del fallback de imágenes está lista en `e43234f` de `feature/webcams-map`.

### Frontend y seguridad

- MapLibre actualizado a 6.14.
- Auditoría de dependencias de producción sin vulnerabilidades conocidas.
- Configuración inicial de despliegue Pages.
- UI y contrato del backend alineados con `24/48/72/120` horas.

## Hallazgos verificados

### GFS

Se ejecutó una descarga real completa contra NOMADS. El ciclo seleccionado fue `2026-10-18T06Z` y la ejecución tardó menos de un minuto.

APCP alterna productos de 3 y 6 horas. Para estos horizontes deben sumarse únicamente las ventanas disjuntas `f006, f012, ..., f120`. El commit `15e2fd9` contiene la corrección y una prueba de regresión.

La resolución es 0,25 grados: sirve para comparación regional, no para representar variaciones finas dentro de Sierra Nevada. No remuestrear presentándolo como mayor resolución.

### ECMWF

Se verificó una descarga real y sin credenciales de precipitación total y nevada acumulada para `24/48/72/120` horas. Fueron aproximadamente 4,8 MB para los cuatro horizontes. No hay implementación guardada todavía.

Debe ser el segundo modelo tras estabilizar GFS. Recortar al bbox, convertir metros de agua a milímetros, generar PNG georreferenciado y añadirlo al mismo contrato multi-modelo.

### WeatherNext 3

El acceso operativo necesita una solicitud externa y allowlist. La aprobación anunciada tarda varios días. Preparar el adaptador y el estado `unavailable`, pero no bloquear el despliegue ni fingir disponibilidad.

### AEMET

No asumir que las salidas numéricas crudas están disponibles mediante OpenData. Integrar únicamente un producto oficial con licencia y endpoint verificables. Mantenerlo como pendiente hasta confirmar ese contrato.

### Hosting actual

- El repositorio remoto es público: `mariopeces/NivoSense`.
- GitHub Pages no está activado todavía; la API devuelve 404.
- No hay secrets ni variables configurados en el repositorio.
- `gs://nivosense-cogs` responde 401 y es privado.
- La autenticación local de `gcloud` está caducada y requiere login interactivo.
- El backend usa URLs públicas de GCS sin autenticación, por lo que no puede leer el bucket privado en su estado actual.

La ruta preferente para el MVP es estática: Actions procesa los datos y Pages sirve PNG/JSON. No hagas depender la vista principal de Cloud Run.

## Integración inmediata

### 1. Integrar forecast sin perder GFSC

Aplica `15e2fd9`. Habrá conflictos en:

```text
frontend/src/App.tsx
frontend/src/components/Map.tsx
frontend/src/lib/horizons.ts
```

Resolución esperada:

- `App.tsx` debe conservar tanto `staticObservationScene` como `weatherOverlay`.
- Debe conservar estados de webcams y añadir estados del manifiesto meteorológico.
- `Map` debe recibir simultáneamente `ndsiImage` y `weatherOverlay`.
- `Map.tsx` debe mantener ambos refs y ejecutar `setNdsiLayer` y `setWeatherLayer` al cargar el estilo.
- `setNdsiLayer` conserva soporte tile/API y PNG/bbox estático.
- `setWeatherLayer` añade la imagen de precipitación sin borrar la capa de nieve.
- En `plus5d`, `+120 horas` y `+5 días` son equivalentes. Usa una sola forma y deja pasar las pruebas.

Después ejecuta:

```powershell
python -m unittest discover -s tests/weather_forecasts -v
python -m unittest discover -s tests -p "test_*.py" -v
cd frontend
npm run build
```

### 2. Consolidar Pages y webcams

No mantengas `pages.yml`, `publish-pages.yml` y un workflow de webcams desplegando Pages de forma independiente. Las ejecuciones concurrentes pueden sobrescribirse.

Usa un único workflow de publicación que:

1. restaure el último artifact válido de observación;
2. restaure el último artifact meteorológico;
3. actualice el catálogo DGT cuando corresponda;
4. compile el frontend una sola vez;
5. valide `index.html`, manifiestos y JSON;
6. despliegue un único artifact Pages.

Del commit `e43234f`, conserva:

- test del catálogo estático;
- fallback visual de imágenes rotas;
- ideas de validación del artifact.

Evita commits horarios automáticos del JSON de webcams: el catálogo puede regenerarse dentro del artifact desplegado sin aumentar el historial de Git.

### 3. Activar el sitio

Cuando el árbol esté limpio, las pruebas pasen y los commits estén listos:

```powershell
git push origin main
```

Después activa Pages con source `GitHub Actions`, desde Settings o mediante la API de GitHub. Lanza el workflow manual y comprueba la URL devuelta por el job de despliegue.

No afirmes que GFSC está actualizado hasta configurar y probar `CDSE_CLIENT_ID` y `CDSE_CLIENT_SECRET`.

## Plan de desarrollo

### Fase 1 — MVP público estático

- Integrar los commits pendientes.
- Unificar publicación Pages.
- Mostrar GFSC si existe; en caso contrario, un estado explícito sin capa.
- Mostrar precipitación GFS en los cuatro horizontes.
- Mantener webcams DGT actualizadas.
- Evitar peticiones a `/rivers`, `/observations` o `/predictions` cuando no exista `VITE_API_URL`.
- Servir estadísticas de cuenca únicamente donde exista JSON real precomputado.
- No mostrar los ficheros de caudal actuales: declaran ser placeholders.
- Mantener rutas en estado vacío porque `data/routes.geojson` contiene cero features.

Criterio de salida: la consola del navegador no presenta 404 propios, todas las secciones muestran datos reales o un empty state, y una recarga directa desde la URL Pages funciona.

### Fase 2 — Comparador meteorológico

- Añadir ECMWF al manifiesto multi-modelo.
- Selector de modelo independiente del selector de horizonte.
- Precipitación total y nevada acumulada separadas.
- Mostrar resolución nativa, hora de ciclo, fecha válida, antigüedad y atribución.
- Añadir WeatherNext y AEMET solo después de disponer de acceso verificable.

Criterio de salida: GFS y ECMWF pueden seleccionarse en los mismos cuatro horizontes y nunca se comparan campos con unidades distintas.

### Fase 3 — Profundidad y volumen

- Preparar DEM, forzamientos horarios y máscaras observadas.
- Ejecutar un modelo distribuido de balance de masa y energía validado.
- Asimilar cobertura GFSC sin convertirla directamente en profundidad.
- Validar profundidad y SWE con observaciones ERHIN u otras estaciones documentadas.
- Calcular VAFN por subcuenca como suma de `SWE × área de píxel / 1e6`.
- Publicar incertidumbre, fecha de forzamiento y cobertura de validación.

Criterio de salida: no se publica mapa de profundidad ni hm³ hasta superar una validación reproducible y documentada.

### Fase 4 — Operación

- Alertas de workflows fallidos.
- Retención y limpieza de artifacts.
- Pruebas de contrato para todos los manifiestos.
- Comprobación periódica de URLs de webcams.
- Caché e invalidación por fecha de ciclo.
- Presupuesto de tamaño y tiempo de Pages/Actions.

## Pruebas obligatorias antes del push

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
python -m unittest discover -s tests/weather_forecasts -v
python -m unittest discover -s backend/tests -v
python -m compileall backend pipelines scripts
cd frontend
npm ci
npm run build
npm audit --omit=dev --audit-level=low
```

Comprueba también:

```powershell
git diff --check
git status --short
```

## Definición de “operativo”

No basta con que los workflows sean válidos. Al terminar deben cumplirse todos estos puntos:

- URL pública accesible.
- Build y despliegue verdes.
- Sin secretos en frontend ni Git.
- Sin llamadas fallidas a un backend no configurado.
- Cobertura, forecast y webcams muestran fecha y fuente.
- Datos ausentes producen empty states, no valores ficticios.
- La actualización de una fuente no borra las otras del sitio.
- El forecast GFS no duplica ventanas de precipitación.
- El repositorio queda limpio y sincronizado con `origin/main`.

## Bloqueos que requieren a Mario

Solo estos pasos necesitan intervención humana o credenciales:

1. aportar credenciales CDSE mediante GitHub Secrets;
2. solicitar acceso operativo a WeatherNext 3;
3. renovar autenticación de GCP si se decide conservar Cloud Run/GCS;
4. confirmar cualquier fuente adicional de webcams cuya licencia no sea inequívoca.

El resto puede completarse autónomamente.
