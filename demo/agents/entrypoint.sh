#!/usr/bin/env bash
# First-run setup so the agents start straight into the demo workspace.
set -euo pipefail

# Claude Code: skip onboarding, pre-approve the API key from the environment,
# and trust /workspace.
if [ -n "${ANTHROPIC_API_KEY:-}" ] && [ ! -f "$HOME/.claude.json" ]; then
  python3 - <<'PY'
import json, os
key = os.environ["ANTHROPIC_API_KEY"]
cfg = {
    "hasCompletedOnboarding": True,
    "customApiKeyResponses": {"approved": [key[-20:]], "rejected": []},
    "projects": {"/workspace": {"hasTrustDialogAccepted": True, "hasCompletedProjectOnboarding": True}},
}
open(os.path.expanduser("~/.claude.json"), "w").write(json.dumps(cfg))
PY
fi

# Codex: log in with the API key from the environment.
if [ -n "${OPENAI_API_KEY:-}" ] && [ ! -f "$HOME/.codex/auth.json" ]; then
  mkdir -p "$HOME/.codex"
  printenv OPENAI_API_KEY | codex login --with-api-key >/dev/null 2>&1 || true
fi

exec "$@"
