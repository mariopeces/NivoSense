# Setup de infraestructura (GCP)

Comandos `gcloud` a ejecutar una sola vez para dejar el proyecto `nivosense` preparado. Región: `europe-west1`.

## 1. Proyecto y APIs

```bash
gcloud config set project nivosense

gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  storage.googleapis.com \
  iamcredentials.googleapis.com
```

## 2. Buckets

```bash
# COGs de predicción (+ GeoJSONs de cuencas y rutas)
gsutil mb -l europe-west1 gs://nivosense-cogs

# Frontend empaquetado
gsutil mb -l europe-west1 gs://nivosense-web
```

**Lectura pública** (demo de hackathon):

```bash
gsutil iam ch allUsers:objectViewer gs://nivosense-cogs
gsutil iam ch allUsers:objectViewer gs://nivosense-web
```

**CORS del bucket de COGs** (para que MapLibre pueda leer tiles desde el navegador si algún día servimos tiles directos desde GCS):

```bash
gsutil cors set deploy/cors.json gs://nivosense-cogs
```

**Servir el bucket web como sitio estático:**

```bash
gsutil web set -m index.html -e index.html gs://nivosense-web
```

## 3. Artifact Registry

```bash
gcloud artifacts repositories create nivosense-docker \
  --repository-format=docker \
  --location=europe-west1
```

## 4. Service account para Cloud Run

```bash
gcloud iam service-accounts create nivosense-api \
  --display-name="NivoSense API runtime"

# Lectura de los COGs
gsutil iam ch \
  serviceAccount:nivosense-api@nivosense.iam.gserviceaccount.com:objectViewer \
  gs://nivosense-cogs
```

## 5. Permisos de Cloud Build

El service account por defecto de Cloud Build (`<PROJECT_NUMBER>@cloudbuild.gserviceaccount.com`) necesita desplegar en Cloud Run:

```bash
PROJECT_NUMBER=$(gcloud projects describe nivosense --format='value(projectNumber)')

gcloud projects add-iam-policy-binding nivosense \
  --member="serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
  --role="roles/run.admin"

gcloud projects add-iam-policy-binding nivosense \
  --member="serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"
```

## 6. Trigger de Cloud Build

Conecta el repo de GitHub al proyecto desde la consola de Cloud Build (Triggers → Connect repository), y después:

```bash
gcloud builds triggers create github \
  --name=nivosense-api-main \
  --repo-owner=<GITHUB_OWNER> \
  --repo-name=NivoSense \
  --branch-pattern='^main$' \
  --included-files='backend/**' \
  --build-config=deploy/cloudbuild.yaml
```

## 7. Verificación

Después del primer push a `main` tocando `backend/**`:

```bash
# Ver la build
gcloud builds list --limit=1

# URL del servicio
gcloud run services describe nivosense-api \
  --region=europe-west1 --format='value(status.url)'

# Health check
curl "$(gcloud run services describe nivosense-api --region=europe-west1 --format='value(status.url)')/health"
```

## 8. Deploy del frontend

Manual, desde local:

```bash
bash deploy/deploy-web.sh
```

URL pública: `https://storage.googleapis.com/nivosense-web/index.html`
