#!/usr/bin/env bash
# Creates the Darwin external-storage integration via API (alternative to the
# Darwin UI: Settings → Storage → New Storage Integration).
# Usage: ./scripts/create_storage_integration.sh <bucket-name> <aws-region> [readonly]
set -euo pipefail

cd "$(dirname "$0")/.."
set -a
# shellcheck source=/dev/null
source .env
set +a
: "${DARWIN_API_KEY:?set DARWIN_API_KEY in .env}"
: "${DARWIN_TEAM_SLUG:?set DARWIN_TEAM_SLUG in .env}"
: "${DARWIN_STORAGE_NAME:?set DARWIN_STORAGE_NAME in .env}"

BUCKET=${1:?usage: $0 <bucket-name> <aws-region> [readonly]}
REGION=${2:?usage: $0 <bucket-name> <aws-region> [readonly]}
READONLY=$([[ "${3:-}" == "readonly" ]] && echo true || echo false)

curl -sf -X POST \
  -H "Authorization: ApiKey ${DARWIN_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"${DARWIN_STORAGE_NAME}\",
    \"provider\": \"aws\",
    \"bucket\": \"${BUCKET}\",
    \"region\": \"${REGION}\",
    \"prefix\": \"\",
    \"readonly\": ${READONLY}
  }" \
  "${DARWIN_BASE_URL}/api/teams/${DARWIN_TEAM_SLUG}/storage"
echo
echo "Storage integration '${DARWIN_STORAGE_NAME}' created (readonly=${READONLY})."
echo "Remember the bucket policy + KMS key policy must grant Darwin's external-storage role — see README."
