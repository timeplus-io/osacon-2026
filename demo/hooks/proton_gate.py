#!/usr/bin/env python3
"""proton_gate — the agent-side end of the loop, for Claude Code and Codex.

One small hook (Python stdlib only) wired into the agent's own lifecycle
hooks. Both agents use the same hook protocol: JSON on stdin, JSON on stdout.

Design: detection is asynchronous, enforcement is synchronous and local.
Proton's materialized views write decisions into agent_actions in the
background; this hook never waits for them. Before each tool call it makes one
lookup — "is there a decision for this session that applies to *this* call?" —
and applies what is already there. A decision therefore takes effect on the
agent's next matching tool call, never on the call that triggered it.

  UserPromptSubmit   append the prompt to agent_session_log; a prompt that
                     contains "[resume]" lifts a halt (writes a 'resume' row)
  PreToolUse         look up agent_actions for this session:
                       interrupt -> aimed at one call (its normalized target).
                                    If this call matches and the interrupt is
                                    fresh (< PROTON_GATE_INTERRUPT_TTL_S), deny
                                    it once; the hint is the reason the model
                                    reads. Any other call runs normally.
                       halt      -> deny every tool call until resumed
  PostToolUse(+Failure)  append the call to agent_session_log; if the session
                     has been halted, return {"continue": false} to stop it

It fails open: if Proton is unreachable or slow (PROTON_GATE_TIMEOUT_S), the
agent runs normally.

Environment:
  PROTON_QUERY_URL             Proton HTTP query endpoint   (default http://proton:8123)
  PROTON_INGEST_URL            Proton HTTP ingest endpoint  (default http://proton:3218)
  PROTON_GATE_AGENT            agent label for the session log (claude-code | codex)
  PROTON_GATE_STATE            state dir                    (default ~/.cache/proton-gate)
  PROTON_GATE_INTERRUPT_TTL_S  how long an interrupt stays armed (default 60)
  PROTON_GATE_TIMEOUT_S        per-request timeout to Proton (default 1.5)
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
TIMEOUT_S = float(os.environ.get("PROTON_GATE_TIMEOUT_S", "1.5"))
INTERRUPT_TTL_S = int(os.environ.get("PROTON_GATE_INTERRUPT_TTL_S", "60"))
RESUME_TOKEN = "[resume]"

# One lookup per hook call. Proton normalizes the incoming call with the same
# agent_call_target() the detectors use, so "is this the call the decision is
# about?" has one definition. Returns:
#   - halt / resume rows newer than what this hook has already applied
#   - interrupts that are still fresh, each with `matches` for this call
ACTIONS_SQL = (
    "SELECT action, detector, target, hint, reason, t, fresh, incoming, "
    "  (target = '' OR incoming = '' OR incoming = target "
    "   OR (length(incoming) >= 4 AND (position(target, incoming) > 0 OR position(incoming, target) > 0))) AS matches "
    "FROM ("
    "  SELECT action, detector, target, hint, reason, "
    "         to_unix_timestamp64_milli(_tp_time) AS t, "
    "         to_unix_timestamp64_milli(now64(3)) - t <= {ttl:int64} * 1000 AS fresh, "
    "         agent_call_target({args:string}) AS incoming "
    "  FROM table(agent_actions) "
    "  WHERE session_id = {sid:string}"
    ") "
    "WHERE (action IN ('halt', 'resume') AND t > {since:int64}) OR (action = 'interrupt' AND fresh) "
    "ORDER BY t FORMAT JSONEachRow"
)


# --------------------------------------------------------------------------
# Proton I/O
# --------------------------------------------------------------------------
def fetch_actions(session_id: str, since_ms: int, call_args: str = "") -> list[dict]:
    qs = urllib.parse.urlencode({"param_sid": session_id, "param_since": since_ms,
                                 "param_ttl": INTERRUPT_TTL_S, "param_args": call_args})
    req = urllib.request.Request(f"{QUERY_URL}/?{qs}", data=ACTIONS_SQL.encode(), method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return [json.loads(line) for line in resp.read().decode().splitlines() if line.strip()]


def ingest(stream: str, row: dict) -> None:
    body = json.dumps({"columns": list(row), "data": [list(row.values())]}).encode()
    req = urllib.request.Request(f"{INGEST_URL}/proton/v1/ingest/streams/{stream}",
                                 data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=TIMEOUT_S).read()
    except Exception:
        pass  # best-effort


def append_log(session_id: str, agent: str, event_type: str, content: str) -> None:
    ingest("agent_session_log", {"session_id": session_id, "agent": agent,
                                 "event_type": event_type, "content": content[:4000]})


# --------------------------------------------------------------------------
# per-session state, so each decision is applied exactly once
# --------------------------------------------------------------------------
class State:
    def __init__(self, session_id: str):
        safe = "".join(ch for ch in session_id if ch.isalnum() or ch in "-_")[:80] or "unknown"
        self.path = STATE_DIR / f"{safe}.json"
        try:
            d = json.loads(self.path.read_text())
        except Exception:
            d = {}
        self.ack_ms: int = d.get("ack_ms", 0)            # halt/resume rows applied up to here
        self.resume_ms: int = d.get("resume_ms", 0)      # decisions before the last resume are void
        self.consumed: list[int] = d.get("consumed", [])  # interrupts already used (their t)
        self.halted: str | None = d.get("halted")

    def save(self) -> None:
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"ack_ms": self.ack_ms, "resume_ms": self.resume_ms,
                                             "consumed": self.consumed[-100:], "halted": self.halted}))
        except Exception:
            pass

    def apply(self, rows: list[dict]) -> list[dict]:
        """Apply halt/resume rows in order; return the interrupts still pending."""
        for r in rows:
            t = int(r["t"])
            if r["action"] in ("halt", "resume") and t > self.ack_ms:
                if r["action"] == "resume":
                    self.halted, self.resume_ms = None, max(self.resume_ms, t)
                elif t > self.resume_ms:
                    self.halted = r["hint"] or r["reason"]
                self.ack_ms = t
        return [r for r in rows if r["action"] == "interrupt"
                and int(r["t"]) > self.resume_ms and int(r["t"]) not in self.consumed]


def summarize_call(tool_name: str, tool_input) -> str:
    if isinstance(tool_input, dict):
        for k in ("command", "cmd", "file_path", "url", "pattern"):
            if k in tool_input:
                v = tool_input[k]
                return f"{tool_name}: {v if isinstance(v, str) else json.dumps(v)}"
    return f"{tool_name}: {json.dumps(tool_input)[:300]}"


def call_args(tool_input) -> str:
    return tool_input if isinstance(tool_input, str) else json.dumps(tool_input or {})


# --------------------------------------------------------------------------
# the decision
# --------------------------------------------------------------------------
def deny(event: str, reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": event, "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def resume(session_id: str, agent: str, by: str) -> None:
    """Lift a halt (and void pending interrupts) for a session. Recorded in agent_actions."""
    ingest("agent_actions", {"session_id": session_id, "action": "resume", "detector": by,
                             "reason": f"resumed by {by}", "hint": "", "tool_name": "", "target": ""})
    state = State(session_id)
    state.halted, state.resume_ms = None, int(time.time() * 1000)
    state.save()
    append_log(session_id, agent, "control", f"resume -> halt lifted by {by}")


def handle(payload: dict, agent: str) -> dict | None:
    event = payload.get("hook_event_name", "")
    sid = str(payload.get("session_id", ""))
    if not sid:
        return None

    if event == "UserPromptSubmit":
        prompt = str(payload.get("prompt", ""))
        append_log(sid, agent, "user_prompt", prompt)
        if RESUME_TOKEN in prompt.lower():
            resume(sid, agent, "user")
        return None

    state = State(sid)

    if event == "PreToolUse":
        tool, tool_input = payload.get("tool_name", ""), payload.get("tool_input")
        try:
            rows = fetch_actions(sid, state.ack_ms, call_args(tool_input))
        except Exception:
            if not state.halted:
                raise          # Proton unreachable: fail open
            rows = []          # ...but a halt we already know about still stands
        pending = state.apply(rows)
        if state.halted:
            state.save()
            append_log(sid, agent, "control", "halt -> blocked tool call")
            return deny("PreToolUse", f"{state.halted} (A person can type {RESUME_TOKEN} to continue.)")
        hit = [r for r in pending if r["matches"]]
        if hit:
            state.consumed += [int(r["t"]) for r in hit]   # one block per decision
            state.save()
            append_log(sid, agent, "control", f"interrupt -> blocked {summarize_call(tool, tool_input)}")
            return deny("PreToolUse", hit[-1]["hint"] or hit[-1]["reason"])
        state.save()
        return None   # no decision, or the agent has already moved on to a different call

    if event in ("PostToolUse", "PostToolUseFailure"):
        ok = event == "PostToolUse"
        append_log(sid, agent, "tool_call",
                   f"{'ok' if ok else 'FAILED'} {summarize_call(payload.get('tool_name', ''), payload.get('tool_input'))}")
        if not state.halted:
            state.apply(fetch_actions(sid, state.ack_ms))
            state.save()
        if state.halted:
            append_log(sid, agent, "control", "halt -> session stopped")
            return {"continue": False,
                    "stopReason": f"Halted by stream policy: {state.halted} Type {RESUME_TOKEN} to continue."}
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
