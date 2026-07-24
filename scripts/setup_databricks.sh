#!/usr/bin/env bash
# One-shot setup: secret scope, target schema, notebook import, and jobs.
# Reads configuration from .env (see .env.sample). Idempotent — safe to re-run.
set -euo pipefail

cd "$(dirname "$0")/.."
if [[ ! -f .env ]]; then
  echo "ERROR: .env not found. Copy .env.sample to .env and fill it in." >&2
  exit 1
fi
set -a
# shellcheck source=/dev/null
source .env
set +a

: "${DARWIN_API_KEY:?set DARWIN_API_KEY in .env}"
: "${DARWIN_TEAM_SLUG:?set DARWIN_TEAM_SLUG in .env}"
: "${DARWIN_STORAGE_NAME:?set DARWIN_STORAGE_NAME in .env}"
: "${SOURCE_PATH:?set SOURCE_PATH in .env}"
: "${DATABRICKS_WAREHOUSE_ID:?set DATABRICKS_WAREHOUSE_ID in .env}"

DB=(databricks)
if [[ -n "${DATABRICKS_PROFILE:-}" ]]; then
  DB+=(--profile "$DATABRICKS_PROFILE")
else
  : "${DATABRICKS_HOST:?set DATABRICKS_PROFILE or DATABRICKS_HOST+DATABRICKS_TOKEN in .env}"
  : "${DATABRICKS_TOKEN:?set DATABRICKS_PROFILE or DATABRICKS_HOST+DATABRICKS_TOKEN in .env}"
  export DATABRICKS_HOST DATABRICKS_TOKEN
fi

echo "==> Secret scope '${SECRET_SCOPE}'"
"${DB[@]}" secrets create-scope "$SECRET_SCOPE" 2>/dev/null || true
"${DB[@]}" secrets put-secret "$SECRET_SCOPE" "$SECRET_KEY" --string-value "$DARWIN_API_KEY"

echo "==> Target schema for ${TARGET_TABLE}"
SCHEMA="${TARGET_TABLE%.*}" # catalog.schema
"${DB[@]}" api post /api/2.0/sql/statements --json "{
  \"warehouse_id\": \"${DATABRICKS_WAREHOUSE_ID}\",
  \"statement\": \"CREATE SCHEMA IF NOT EXISTS ${SCHEMA}\",
  \"wait_timeout\": \"50s\"
}" >/dev/null
echo "    ${SCHEMA} ready"

echo "==> Importing notebooks to ${WORKSPACE_DIR}"
"${DB[@]}" workspace mkdirs "$WORKSPACE_DIR"
for nb in notebooks/01_register_external_items notebooks/02_export_annotations_to_delta; do
  "${DB[@]}" workspace import "${WORKSPACE_DIR}/$(basename "$nb")" \
    --file "${nb}.py" --format SOURCE --language PYTHON --overwrite
done

base_params() { # shared notebook parameters, JSON object
  cat <<JSON
{
  "darwin_base_url": "${DARWIN_BASE_URL}",
  "team_slug": "${DARWIN_TEAM_SLUG}",
  "dataset_slug": "${DARWIN_DATASET_SLUG}",
  "storage_name": "${DARWIN_STORAGE_NAME}",
  "source_path": "${SOURCE_PATH}",
  "target_table": "${TARGET_TABLE}",
  "secret_scope": "${SECRET_SCOPE}",
  "secret_key": "${SECRET_KEY}"
}
JSON
}

create_or_reset_job() { # $1 job name, $2 job-settings JSON
  local name=$1 settings=$2 job_id
  job_id=$("${DB[@]}" jobs list --name "$name" --output json 2>/dev/null |
    python3 -c "import json,sys; j=json.load(sys.stdin); print(j[0]['job_id'] if j else '')" || true)
  if [[ -n "$job_id" ]]; then
    "${DB[@]}" jobs reset "$job_id" --json "{\"job_id\": ${job_id}, \"new_settings\": ${settings}}" >/dev/null
    echo "    updated job '${name}' (id ${job_id})"
  else
    "${DB[@]}" jobs create --json "$settings" >/dev/null
    echo "    created job '${name}'"
  fi
}

echo "==> Jobs"
create_or_reset_job "v7-darwin-register" "{
  \"name\": \"v7-darwin-register\",
  \"tasks\": [{
    \"task_key\": \"register\",
    \"notebook_task\": {
      \"notebook_path\": \"${WORKSPACE_DIR}/01_register_external_items\",
      \"base_parameters\": $(base_params)
    }
  }]
}"

SCHEDULE_BLOCK=""
if [[ -n "${SYNC_SCHEDULE_CRON:-}" ]]; then
  SCHEDULE_BLOCK=", \"schedule\": {\"quartz_cron_expression\": \"${SYNC_SCHEDULE_CRON}\", \"timezone_id\": \"${SYNC_SCHEDULE_TZ:-UTC}\"}"
fi
create_or_reset_job "v7-darwin-export-sync" "{
  \"name\": \"v7-darwin-export-sync\",
  \"tasks\": [{
    \"task_key\": \"export\",
    \"notebook_task\": {
      \"notebook_path\": \"${WORKSPACE_DIR}/02_export_annotations_to_delta\",
      \"base_parameters\": $(base_params)
    }
  }]${SCHEDULE_BLOCK}
}"

echo
echo "Done. Next steps:"
echo "  1. Run the 'v7-darwin-register' job (or the notebook) to register your files in Darwin."
echo "  2. Annotate in Darwin."
echo "  3. Run 'v7-darwin-export-sync' (scheduled: ${SYNC_SCHEDULE_CRON:-not scheduled}) and query ${TARGET_TABLE}."
