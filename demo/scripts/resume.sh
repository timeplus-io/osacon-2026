#!/usr/bin/env bash
# Lift a halt for one agent session (operator side). Writes a 'resume' row to
# agent_actions — the same thing the hook does when a person types [resume] in
# the session — so the audit trail shows who resumed it and when. Pending
# interrupts for the session are voided too.
#
#   scripts/resume.sh <session_id> [who]
set -euo pipefail
cd "$(dirname "$0")/.."
sid="${1:?usage: scripts/resume.sh <session_id> [who]}"
who="${2:-operator}"
esc() { printf "%s" "$1" | sed "s/'/''/g"; }
docker compose exec -T proton proton client --query \
  "INSERT INTO agent_actions (session_id, action, detector, reason) VALUES ('$(esc "$sid")', 'resume', '$(esc "$who")', 'resumed by $(esc "$who")')"
echo "resumed $sid"
