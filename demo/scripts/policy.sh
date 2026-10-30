#!/usr/bin/env bash
# Open or close the loop on stage: the policy view is what turns alerts into
# decisions the hooks act on.
#   scripts/policy.sh off     drop mv_policy  -> alerts still fire, agents are never blocked
#   scripts/policy.sh on      create it again -> the next alert becomes a decision
#   scripts/policy.sh status
set -euo pipefail
cd "$(dirname "$0")/.."
case "${1:-status}" in
  off)    docker compose exec -T proton proton client -q "DROP VIEW IF EXISTS mv_policy" && echo "loop OPEN: mv_policy dropped" ;;
  on)     docker compose exec -T proton proton client --multiquery < sql/04_policy.sql && echo "loop CLOSED: mv_policy running" ;;
  status) n=$(docker compose exec -T proton proton client -q "SELECT count() FROM system.tables WHERE name = 'mv_policy'")
          [ "$n" = "1" ] && echo "loop CLOSED (mv_policy running)" || echo "loop OPEN (no mv_policy)" ;;
  *)      echo "usage: $0 off|on|status" >&2; exit 2 ;;
esac
