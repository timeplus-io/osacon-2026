#!/usr/bin/env bash
# Drop and recreate the demo schema so the live views start empty — run it
# right before going on stage, or after changing BUDGET_* in .env.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose exec -T proton proton client --multiquery < sql/99_teardown.sql
docker compose run --rm proton-init
