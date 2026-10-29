#!/usr/bin/env python3
"""proton_gate — the agent-side end of the loop, for Claude Code and Codex.

One small hook (Python stdlib only) wired into the agent's own lifecycle
hooks. Both agents use the same hook protocol: JSON on stdin, JSON on stdout.

  UserPromptSubmit   append the prompt to agent_session_log
  PreToolUse         read new rows from agent_actions for this session:
                       interrupt -> deny this tool call; the hint becomes the
                                    reason the model sees, and it adapts
                       halt      -> deny every further tool call
  PostToolUse(+Failure)  append the call to agent_session_log; if the session
                     has been halted, return {"continue": false} to stop it

The detection itself happens in Proton, outside the agent — this hook only
reads the decision. It fails open: if Proton is unreachable the agent runs
normally.

Environment:
  PROTON_QUERY_URL   Proton HTTP query endpoint   (default http://proton:8123)
  PROTON_INGEST_URL  Proton HTTP ingest endpoint  (default http://proton:3218)
  PROTON_GATE_AGENT  agent label for the session log (claude-code | codex)
  PROTON_GATE_STATE  state dir                    (default ~/.cache/proton-gate)
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

QUERY_URL = os.environ.get("PROTON_QUERY_URL", "http://proton:8123")
INGEST_URL = os.environ.get("PROTON_INGEST_URL", "http://proton:3218")
STATE_DIR = Path(os.environ.get("PROTON_GATE_STATE", Path.home() / ".cache" / "proton-gate"))
TIMEOUT_S = 1.5

ACTIONS_SQL = (
    "SELECT action, reason, hint, to_unix_timestamp64_milli(_tp_time) AS t "
    "FROM table(agent_actions) "
    "WHERE session_id = {sid:string} AND to_unix_timestamp64_milli(_tp_time) > {since:int64} "
    "ORDER BY t FORMAT JSONEachRow"
)


# --------------------------------------------------------------------------
# Proton I/O
# --------------------------------------------------------------------------
def fetch_actions(session_id: str, since_ms: int) -> list[dict]:
    qs = urllib.parse.urlencode({"param_sid": session_id, "param_since": since_ms})
    req = urllib.request.Request(f"{QUERY_URL}/?{qs}", data=ACTIONS_SQL.encode(), method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return [json.loads(line) for line in resp.read().decode().splitlines() if line.strip()]


def append_log(session_id: str, agent: str, event_type: str, content: str) -> None:
    body = json.dumps({
        "columns": ["session_id", "agent", "event_type", "content"],
        "data": [[session_id, agent, event_type, content[:4000]]],
    }).encode()
    req = urllib.request.Request(f"{INGEST_URL}/proton/v1/ingest/streams/agent_session_log",
                                 data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=TIMEOUT_S).read()
    except Exception:
        pass  # the log is best-effort


# --------------------------------------------------------------------------
# per-session state: which actions we've already applied, and whether halted
# --------------------------------------------------------------------------
class State:
    def __init__(self, session_id: str):
        safe = "".join(ch for ch in session_id if ch.isalnum() or ch in "-_")[:80] or "unknown"
        self.path = STATE_DIR / f"{safe}.json"
        try:
            d = json.loads(self.path.read_text())
        except Exception:
            d = {}
        self.ack_ms: int = d.get("ack_ms", 0)
        self.halted: str | None = d.get("halted")

    def save(self) -> None:
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"ack_ms": self.ack_ms, "halted": self.halted}))
        except Exception:
            pass


def summarize_call(tool_name: str, tool_input) -> str:
    if isinstance(tool_input, dict):
        for k in ("command", "cmd", "file_path", "url", "pattern"):
            if k in tool_input:
                v = tool_input[k]
                return f"{tool_name}: {v if isinstance(v, str) else json.dumps(v)}"
    return f"{tool_name}: {json.dumps(tool_input)[:300]}"


# --------------------------------------------------------------------------
# the decision
# --------------------------------------------------------------------------
def deny(event: str, reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": event, "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def handle(payload: dict, agent: str) -> dict | None:
    event = payload.get("hook_event_name", "")
    sid = str(payload.get("session_id", ""))
    if not sid:
        return None

    if event == "UserPromptSubmit":
        append_log(sid, agent, "user_prompt", str(payload.get("prompt", "")))
        return None

    state = State(sid)

    if event == "PreToolUse":
        if not state.halted:
            new = fetch_actions(sid, state.ack_ms)
            if new:
                state.ack_ms = max(a["t"] for a in new)
                halts = [a for a in new if a["action"] == "halt"]
                if halts:
                    state.halted = halts[-1]["hint"] or halts[-1]["reason"]
                state.save()
                interrupts = [a for a in new if a["action"] == "interrupt"]
                if not state.halted and interrupts:
                    hint = interrupts[-1]["hint"] or interrupts[-1]["reason"]
                    append_log(sid, agent, "control", f"interrupt -> blocked {summarize_call(payload.get('tool_name', ''), payload.get('tool_input'))}")
                    return deny("PreToolUse", hint)
        if state.halted:
            append_log(sid, agent, "control", "halt -> blocked tool call")
            return deny("PreToolUse", state.halted)
        return None

    if event in ("PostToolUse", "PostToolUseFailure"):
        ok = event == "PostToolUse"
        append_log(sid, agent, "tool_call",
                   f"{'ok' if ok else 'FAILED'} {summarize_call(payload.get('tool_name', ''), payload.get('tool_input'))}")
        if not state.halted:
            halts = [a for a in fetch_actions(sid, state.ack_ms) if a["action"] == "halt"]
            if halts:
                state.halted = halts[-1]["hint"] or halts[-1]["reason"]
                state.save()
        if state.halted:
            append_log(sid, agent, "control", "halt -> session stopped")
            return {"continue": False, "stopReason": f"Halted by stream policy: {state.halted}"}
        return None

    return None


def main() -> int:
    agent = os.environ.get("PROTON_GATE_AGENT", "agent")
    try:
        payload = json.load(sys.stdin)
        out = handle(payload, agent)
    except Exception as exc:  # fail open
        print(f"proton_gate: {exc}", file=sys.stderr)
        return 0
    if out is not None:
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
