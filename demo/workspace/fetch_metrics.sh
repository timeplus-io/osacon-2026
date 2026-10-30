#!/usr/bin/env bash
# Pull the last hour of error-rate metrics for checkout-api from the metrics API.
# Output: CSV (timestamp,service,error_rate_pct).
set -uo pipefail
METRICS_API="${METRICS_API:-http://metrics.internal:8080}"
query='error_rate{service="checkout-api"}[1h]'
echo "fetching $query from $METRICS_API ..." >&2
curl -sS --fail-with-body --max-time 10 -G "$METRICS_API/api/v1/query" \
  --data-urlencode "query=$query" --data-urlencode "format=csv"
