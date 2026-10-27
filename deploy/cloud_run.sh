#!/usr/bin/env bash
# Deploy to Cloud Run. One service, one instance, CPU always on (the sync loop runs in-process).
# Prereqs: gcloud logged into the right account/project, APIs enabled, Neon DATABASE_URL, OAuth client, OpenRouter key.
#   PROJECT=my-project REGION=us-central1 SERVICE=docintel bash deploy/cloud_run.sh
set -euo pipefail
PROJECT="${PROJECT:?set PROJECT}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-docintel}"
REPO="${REPO:-docintel}"
ENV_FILE="${ENV_FILE:-.env}"
IMAGE="$REGION-docker.pkg.dev/$PROJECT/$REPO/app:$(git rev-parse --short HEAD 2>/dev/null || date +%s)"

val() { grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2- | sed -e 's/^ *//' -e 's/ *#.*$//' -e 's/^"//' -e 's/"$//'; }
put_secret() {  # name, value — creates or adds a version, never echoes the value
  local name="$1" value="$2"
  [ -z "$value" ] && { echo "skip $name (empty)"; return; }
  if gcloud secrets describe "$name" --project "$PROJECT" >/dev/null 2>&1; then
    printf '%s' "$value" | gcloud secrets versions add "$name" --project "$PROJECT" --data-file=- >/dev/null
  else
    printf '%s' "$value" | gcloud secrets create "$name" --project "$PROJECT" --replication-policy=automatic --data-file=- >/dev/null
  fi
  echo "secret $name ok"
}

gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com --project "$PROJECT"
gcloud artifacts repositories describe "$REPO" --location "$REGION" --project "$PROJECT" >/dev/null 2>&1 || \
  gcloud artifacts repositories create "$REPO" --repository-format=docker --location "$REGION" --project "$PROJECT"

put_secret OPENROUTER_API_KEY "$(val OPENROUTER_API_KEY)"
put_secret GOOGLE_CLIENT_SECRET "$(val GOOGLE_CLIENT_SECRET)"
put_secret APP_SECRET "$(val APP_SECRET)"
put_secret DATABASE_URL "$(val DATABASE_URL)"

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
SA="$PROJECT_NUMBER-compute@developer.gserviceaccount.com"
for s in OPENROUTER_API_KEY GOOGLE_CLIENT_SECRET APP_SECRET DATABASE_URL; do
  gcloud secrets add-iam-policy-binding "$s" --project "$PROJECT" --member "serviceAccount:$SA" --role roles/secretmanager.secretAccessor >/dev/null
done

echo "building $IMAGE"
gcloud builds submit --tag "$IMAGE" --project "$PROJECT" --quiet
BASE_URL="${BASE_URL:-https://$SERVICE-$PROJECT_NUMBER.$REGION.run.app}"
gcloud run deploy "$SERVICE" --image "$IMAGE" --project "$PROJECT" --region "$REGION" \
  --allow-unauthenticated --min-instances 1 --max-instances 1 --no-cpu-throttling --memory 1Gi --cpu 1 --timeout 300 \
  --set-env-vars "GOOGLE_CLIENT_ID=$(val GOOGLE_CLIENT_ID),BASE_URL=$BASE_URL,MODEL=$(val MODEL),FALLBACK_MODEL=$(val FALLBACK_MODEL),PDF_ENGINE=$(val PDF_ENGINE),SYNC_INTERVAL_SECONDS=$(val SYNC_INTERVAL_SECONDS)" \
  --set-secrets "OPENROUTER_API_KEY=OPENROUTER_API_KEY:latest,GOOGLE_CLIENT_SECRET=GOOGLE_CLIENT_SECRET:latest,APP_SECRET=APP_SECRET:latest,DATABASE_URL=DATABASE_URL:latest"
echo
# Alternative to the in-process loop (lets the service scale to zero): Cloud Scheduler calls /api/sync every minute.
# Set SYNC_INTERVAL_SECONDS=0 to disable the in-process loop, deploy with --min-instances 0, then:
#   gcloud scheduler jobs create http docintel-sync --project "$PROJECT" --location "$REGION" --schedule "* * * * *" \
#     --uri "$BASE_URL/api/sync" --http-method POST --headers "Cookie=docintel_app=<signed cookie if APP_PASSWORD is set>"
echo "deployed: $BASE_URL"
echo "add this redirect URI to the OAuth client if you have not: $BASE_URL/api/auth/google/callback"
curl -s "$BASE_URL/api/health" && echo
