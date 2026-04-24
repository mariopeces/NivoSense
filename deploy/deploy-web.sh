#!/usr/bin/env bash
set -euo pipefail

# Despliega el frontend a gs://nivosense-web.
# Uso: ./deploy/deploy-web.sh

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="${ROOT}/frontend"
BUCKET="gs://nivosense-web"

API_URL="${VITE_API_URL:-}"
if [[ -z "${API_URL}" ]]; then
  API_URL="$(gcloud run services describe nivosense-api \
    --region=europe-west1 \
    --format='value(status.url)')"
fi

echo "Building frontend con VITE_API_URL=${API_URL}"
cd "${FRONTEND_DIR}"
VITE_API_URL="${API_URL}" npm run build

echo "Subiendo dist/ a ${BUCKET}"
gsutil -m rsync -d -r dist "${BUCKET}"

echo "Deploy completado: ${BUCKET}"
