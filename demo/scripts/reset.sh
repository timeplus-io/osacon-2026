#!/usr/bin/env bash
# Drop and recreate the demo schema — run this right before going on stage so
# the live queries start from an empty slate.
#
#   scripts/reset.sh            # docker compose stack (default)
#   scripts/reset.sh --local    # local proton binary, direct mode (no Kafka)
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "${1:-}" == "--local" ]]; then
  "${PROTON_BIN:-proton}" client --multiquery < sql/99_teardown.sql
  scripts/setup.sh
else
  docker compose exec -T proton proton client --multiquery < sql/99_teardown.sql
  docker compose run --rm proton-init
fi
