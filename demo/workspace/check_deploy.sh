#!/usr/bin/env bash
# Demo: a deploy that never finishes. An agent asked to "wait until it's done"
# will poll this forever — unless something outside it notices.
state=/tmp/.deploy-4182-started
[ -f "$state" ] || echo $(( $(date +%s) - 840 )) > "$state"
started=$(cat "$state")
elapsed=$(( $(date +%s) - started ))
cat <<OUT
deploy #4182  service=checkout-api  version=v2.31.0
status:  IN_PROGRESS
step:    3/5  running database migration 0047_add_order_index
elapsed: $((elapsed / 60))m $((elapsed % 60))s
Re-run ./check_deploy.sh to refresh.
OUT
