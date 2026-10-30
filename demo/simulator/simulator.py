#!/usr/bin/env python3
"""Offline stand-in for Claude Code / Codex — same signal, same feedback path.

Use it to rehearse without an API key or network, as a stage fallback, and in
the automated tests. It behaves like a coding agent with a scripted "model",
and everything around the model is the real thing:

  * emits OpenTelemetry log events (tool_result, api_request) over OTLP/HTTP
    to the Collector, with the same attributes Claude Code uses
  * calls hooks/proton_gate.py's handler at the same points Claude Code and
    Codex call their hooks (UserPromptSubmit, PreToolUse, PostToolUse)

    simulator.py --scenario loop      # polls a stuck deploy until Proton interrupts it
    simulator.py --scenario flaky     # retries a dead upstream; Proton says fall back
    simulator.py --scenario burn      # re-reads everything each step; Proton halts it
    simulator.py --scenario normal    # nothing fires
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import uuid
from pathlib import Path

from opentelemetry._logs import LogRecord
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource

for p in (Path("/opt/demo/hooks"), Path(__file__).resolve().parent.parent / "hooks"):
    if (p / "proton_gate.py").exists():
        sys.path.insert(0, str(p))
        break
import proton_gate  # noqa: E402

MODEL = "scripted-model"

# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------
COLOR = sys.stdout.isatty() or bool(os.environ.get("FORCE_COLOR"))
def c(code, s): return f"\033[{code}m{s}\033[0m" if COLOR else s
DIM, BOLD, RED, GREEN, YELLOW, CYAN, MAGENTA = "2", "1", "31", "32", "33", "36", "35"
T0 = time.time()
def ts(): return c(DIM, f"[{time.time() - T0:6.2f}s]")


# --------------------------------------------------------------------------
# tools (the same scripts the real agents see in /workspace)
# --------------------------------------------------------------------------
def run_tool(scenario: str, call: dict) -> tuple[bool, str]:
    time.sleep(random.uniform(0.15, 0.3))
    cmd = call.get("command", "")
    if "check_deploy" in cmd:
        return True, "deploy #4182 status: IN_PROGRESS (step 3/5: database migration 0047_add_order_index)"
    if "fetch_metrics" in cmd:
        return False, "curl: (22) The requested URL returned error: 503 (metrics proxy is restarting; retry in a few seconds)"
    if "metrics-cache" in cmd:
        return True, "timestamp,service,error_rate_pct ... 60 rows (spike to 3.4% at 09:38-09:44)"
    if call.get("file_path"):
        return True, "lorem " * 4000      # a long document
    return True, "ok"


# --------------------------------------------------------------------------
# the scripted "model"
# --------------------------------------------------------------------------
GOALS = {
    "loop":   "Deploy #4182 is rolling out. Keep checking it until it finishes, then tell me the result.",
    "flaky":  "Pull the last hour of error-rate metrics for checkout-api and summarize them.",
    "burn":   "Read all the postmortems and write a summary of recurring root causes.",
    "normal": "What does ./check_deploy.sh report right now?",
}


def decide(scenario: str, step: int, blocked: list[str]) -> tuple[str, dict | None, str | None]:
    """-> (thought, tool_call or None, final_answer or None)"""
    if scenario == "normal":
        if step == 1:
            return "Run the status script.", {"tool": "Bash", "command": "./check_deploy.sh"}, None
        return "Done.", None, "The deploy is IN_PROGRESS at step 3/5 (database migration)."
    if scenario == "loop":
        if blocked:
            return "The deploy is not progressing; report instead of polling.", None, \
                   "Deploy #4182 has been stuck at step 3/5 (database migration) for 15+ minutes. Check the migration lock."
        return "Still in progress — wait and check again.", {"tool": "Bash", "command": f"sleep {random.choice([5, 10])} && ./check_deploy.sh"}, None
    if scenario == "flaky":
        if "used-cache" in blocked:
            return "Summarize the cached data.", None, "From the cached snapshot: error rate ~0.5%, with a spike to 3.4% at 09:38-09:44."
        if blocked:
            return "The metrics API is down; use the cached snapshot instead.", {"tool": "Bash", "command": "cat metrics-cache/error_rate_last_1h.csv"}, None
        return "Transient error — retry.", {"tool": "Bash", "command": "./fetch_metrics.sh"}, None
    if scenario == "burn":
        return f"Read postmortem {step} in full.", {"tool": "Read", "file_path": f"/workspace/postmortems/PM-{2026100 + (step % 8) + 1}.md"}, None
    raise ValueError(scenario)


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", choices=list(GOALS), default="loop")
    ap.add_argument("--session-id", default=None)
    ap.add_argument("--otlp-endpoint", default=os.environ.get("OTLP_ENDPOINT", "http://otel-collector:4318"))
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--no-control", action="store_true", help="don't consult Proton (the loop left open)")
    a = ap.parse_args()

    sid = a.session_id or f"sim-{a.scenario}-{uuid.uuid4().hex[:6]}"
    provider = LoggerProvider(resource=Resource.create({"service.name": "simulator"}))
    provider.add_log_record_processor(BatchLogRecordProcessor(
        OTLPLogExporter(endpoint=f"{a.otlp_endpoint.rstrip('/')}/v1/logs"), schedule_delay_millis=200))
    otel = provider.get_logger("simulator")

    def emit(event: str, **attrs):
        otel.emit(LogRecord(timestamp=time.time_ns(), body=f"simulator.{event}",
                            attributes={"event.name": event, "session.id": sid, **{k: str(v) for k, v in attrs.items()}}))

    def hook(event: str, **payload) -> dict | None:
        if a.no_control and event != "UserPromptSubmit":
            return None
        try:
            return proton_gate.handle({"hook_event_name": event, "session_id": sid, **payload}, "simulator")
        except Exception as exc:
            print(c(DIM, f"  (gate unavailable: {exc})"))
            return None

    goal = GOALS[a.scenario]
    print(c(BOLD, f"\nsession {sid}") + c(DIM, f"  scenario={a.scenario} control={'off' if a.no_control else 'on'}"))
    print(f"{ts()} {c(CYAN, 'user ')} {goal}")
    hook("UserPromptSubmit", prompt=goal)

    context_tokens, blocked, outcome, rc = 600, [], "max_steps", 1
    for step in range(1, a.max_steps + 1):
        # model call
        time.sleep(random.uniform(0.3, 0.45))
        thought, call, answer = decide(a.scenario, step, blocked)
        out_tok = random.randint(60, 160)
        emit("api_request", model=MODEL, input_tokens=context_tokens, output_tokens=out_tok, duration_ms=400)
        print(f"{ts()} {c(YELLOW, 'model')} {thought} {c(DIM, f'({context_tokens:,} in / {out_tok} out)')}")
        if answer:
            print(f"{ts()} {c(GREEN, '✔ answer')} {answer}")
            outcome, rc = "answered", 0
            break

        args = {k: v for k, v in call.items() if k != "tool"}
        shown = args.get("command") or args.get("file_path")
        # PreToolUse — the gate
        verdict = hook("PreToolUse", tool_name=call["tool"], tool_input=args)
        if verdict and verdict.get("hookSpecificOutput", {}).get("permissionDecision") == "deny":
            reason = verdict["hookSpecificOutput"]["permissionDecisionReason"]
            print(f"{ts()} {c(MAGENTA, '◀ hook ')} {c(BOLD, 'blocked')} {call['tool']}({shown})")
            print(f"{' ' * 9} {c(MAGENTA, '  reason →')} {c(DIM, reason)}")
            if "[resume]" in reason:  # a halt (budget, or escalation)
                outcome, rc = "halted", 2
                print(f"{ts()} {c(RED, '■ halted by policy')}")
                break
            blocked.append(reason)
            context_tokens += len(reason) // 4
            continue

        ok, result = run_tool(a.scenario, args)
        if ok and "metrics-cache" in str(shown):
            blocked.append("used-cache")
        emit("tool_result", tool_name=call["tool"], success="true" if ok else "false", duration_ms=250,
             tool_input=json.dumps(args), **({} if ok else {"error": result[:200]}))
        short = result if len(result) < 80 else result[:77] + "..."
        print(f"{ts()} {c(CYAN if ok else RED, 'tool ')} {call['tool']}({shown}) → {c(DIM, short)}")
        context_tokens += len(result) // 4 + 40

        post = hook("PostToolUse" if ok else "PostToolUseFailure", tool_name=call["tool"], tool_input=args)
        if post and post.get("continue") is False:
            print(f"{ts()} {c(MAGENTA, '◀ hook ')} {c(BOLD, 'stop')}: {c(DIM, post.get('stopReason', ''))}")
            print(f"{ts()} {c(RED, '■ halted by policy')}")
            outcome, rc = "halted", 2
            break

    provider.force_flush()
    provider.shutdown()
    print(c(BOLD, f"outcome: {outcome}") + c(DIM, f"  ({time.time() - T0:.1f}s)\n"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
