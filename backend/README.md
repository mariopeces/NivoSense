# Backend

API FastAPI que sirve los tiles de NDSI y las estadísticas por cuenca y ruta.

## Local

```bash
python -m venv .venv
source .venv/Scripts/activate   # Git Bash en Windows; en Linux/Mac: .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8080
```

Comprueba:

```bash
curl http://localhost:8080/health
curl http://localhost:8080/layers
```

## Docker

```bash
docker build -t nivosense-api:local .
docker run -p 8080:8080 nivosense-api:local
```

## Estructura

- `main.py` — app FastAPI.
- `layers.yaml` — manifiesto de capas NDSI disponibles (horizontes de predicción y ruta al COG en GCS).
- `Dockerfile` — imagen que despliega Cloud Build a Cloud Run.
