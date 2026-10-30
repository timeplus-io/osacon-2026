#!/usr/bin/env bash
# Open or close the loop on stage. The policy view is what turns alerts into
# decisions the hooks act on; pausing it leaves the detectors running.
#   scripts/policy.sh off     SYSTEM PAUSE  mv_policy -> alerts still fire, nothing reaches the agents
#   scripts/policy.sh on      SYSTEM RESUME mv_policy -> replays the alerts that fired while paused
#                             (each becomes a decision now), then continues live
#   scripts/policy.sh status  running or paused: a view's background query has query_id '.mv-<view uuid>'
#                             in system.processes, and a paused view has none (don't match on query text:
#                             Grafana's streaming panels read agent_alerts too)
# Resume before `docker compose down`: Proton asks you not to restart while a view is paused.
set -euo pipefail
cd "$(dirname "$0")/.."
pc() { docker compose exec -T proton proton client -q "$1"; }
running() { [ "$(pc "SELECT count() FROM system.processes WHERE query_id = (SELECT concat('.mv-', to_string(uuid)) FROM system.tables WHERE database = current_database() AND name = 'mv_policy')")" = "1" ]; }
case "${1:-status}" in
  off)    pc "SYSTEM PAUSE MATERIALIZED VIEW mv_policy"  && echo "loop OPEN: mv_policy paused (detectors still running)" ;;
  on)     pc "SYSTEM RESUME MATERIALIZED VIEW mv_policy" && echo "loop CLOSED: mv_policy resumed (backlog replayed, now live)" ;;
  status) running && echo "loop CLOSED (mv_policy running)" || echo "loop OPEN (mv_policy paused)" ;;
  *)      echo "usage: $0 off|on|status" >&2; exit 2 ;;
esac
