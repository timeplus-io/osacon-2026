#!/usr/bin/env bash
# Show the status of a checkout-api deploy (default: the one in progress).
# Usage: ./check_deploy.sh [deploy-id]
set -euo pipefail
DEPLOY_API="${DEPLOY_API:-http://deploy-api:8080}"
id="${1:-4182}"
curl -sS --fail --max-time 10 -H 'Accept: text/plain' "$DEPLOY_API/v1/deploys/$id"
