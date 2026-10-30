#!/usr/bin/env python3
"""End-to-end test of the loop, through Kafka.

Needs: Proton (schema applied), a Kafka broker, and an OTLP endpoint that
writes to the `otlp_logs` topic (the real Collector, or tests/mini_collector.py).

Part 1 — simulator: runs every scenario (OTel logs -> Collector -> Kafka ->
          Proton -> hook gate) and checks the outcome.
Part 2 — real agent payloads: sends Claude Code- and Codex-shaped OTLP log
          events to Kafka and calls hooks/proton_gate.py the way each agent
          would, checking the hook blocks / stops at the right moment.

    python tests/e2e_test.py [--kafka localhost:9092] [--otlp http://localhost:4318]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEMO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(DEMO / "hooks"))

QUERY = os.environ.setdefault("PROTON_QUERY_URL", "http://localhost:8123")
os.environ.setdefault("PROTON_INGEST_URL", "http://localhost:3218")
os.environ.setdefault("PROTON_GATE_STATE", f"/tmp/proton-gate-test-{uuid.uuid4().hex[:6]}")

import proton_gate  # noqa: E402
from otlp_fixtures import (claude_api_request, claude_tool_result, codex_tool_result,  # noqa: E402
                           codex_usage, logs_payload)


def q(sql: str, **params) -> list[dict]:
    qs = urllib.parse.urlencode({f"param_{k}": v for k, v in params.items()})
    req = urllib.request.Request(f"{QUERY}/?{qs}", data=(sql + " FORMAT JSONEachRow").encode(), method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return [json.loads(x) for x in r.read().decode().splitlines() if x.strip()]


def ddl(sql: str) -> None:
    """Run a statement with no result set (CREATE / DROP)."""
    req = urllib.request.Request(f"{QUERY}/", data=sql.encode(), method="POST")
    urllib.request.urlopen(req, timeout=10).read()


def alert_count(sid: str, detector: str, n: int, wait_s: float = 8.0) -> int:
    """Number of alerts of one detector for a session; polls until at least n."""
    deadline = time.time() + wait_s
    while True:
        got = q("SELECT count() AS n FROM table(agent_alerts) WHERE session_id = {s:string} AND detector = {d:string}",
                s=sid, d=detector)[0]["n"]
        if int(got) >= n or time.time() > deadline:
            return int(got)
        time.sleep(0.5)


def detectors(sid: str, want: set[str] | None = None, wait_s: float = 8.0) -> set[str]:
    """Alerts for a session; polls (up to wait_s) until `want` shows up, since
    freshly written rows take a moment to become visible to table() queries."""
    deadline = time.time() + wait_s
    while True:
        got = {r["detector"] for r in q("SELECT detector FROM table(agent_alerts) WHERE session_id = {s:string}", s=sid)}
        if not want or want <= got or time.time() > deadline:
            return got
        time.sleep(0.5)


def actions(sid: str, n: int = 1, wait_s: float = 10.0) -> list[dict]:
    """Decisions for a session, oldest first; polls until at least n are visible."""
    deadline = time.time() + wait_s
    while True:
        rows = q("SELECT action, detector, target, reason FROM table(agent_actions) WHERE session_id = {s:string} "
                 "ORDER BY _tp_time", s=sid)
        if len(rows) >= n or time.time() > deadline:
            return rows
        time.sleep(0.5)


def until_denied(fn, wait_s: float = 10.0) -> dict | None:
    """Call a PreToolUse check until it denies (a non-deny doesn't consume anything)."""
    deadline = time.time() + wait_s
    while True:
        v = fn()
        if (v and v.get("hookSpecificOutput", {}).get("permissionDecision") == "deny") or time.time() > deadline:
            return v
        time.sleep(0.5)


def reason(v: dict | None) -> str:
    return (v or {}).get("hookSpecificOutput", {}).get("permissionDecisionReason", "")


failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}{('  — ' + detail) if detail else ''}")
    if not cond:
        failures.append(name)


def part1_simulator(otlp: str) -> None:
    print("\n# simulator (OTel logs -> Kafka -> Proton -> hook)")
    expect = {"normal": (0, set()), "loop": (0, {"tool_loop"}), "flaky": (0, {"tool_errors"}), "burn": (2, {"budget"})}
    run = uuid.uuid4().hex[:6]
    for scenario, (want_rc, want_det) in expect.items():
        sid = f"t-{run}-{scenario}"
        p = subprocess.run([sys.executable, str(DEMO / "simulator" / "simulator.py"), "--scenario", scenario,
                            "--session-id", sid, "--otlp-endpoint", otlp], capture_output=True, text=True, timeout=180)
        time.sleep(2)
        got = detectors(sid, want_det)
        events = q("SELECT count() AS n FROM table(agent_events) WHERE session_id = {s:string}", s=sid)[0]["n"]
        ok = p.returncode == want_rc and want_det <= got and (want_det or not got) and int(events) > 0
        check(f"sim {scenario}", ok, f"rc={p.returncode} detectors={sorted(got) or '-'} events={events}")
        if not ok:
            print(p.stdout[-1500:], p.stderr[-1500:])


def part2_agent_payloads(kafka: str) -> None:
    from kafka import KafkaProducer
    print("\n# Claude Code / Codex payloads + hook protocol")
    prod = KafkaProducer(bootstrap_servers=kafka)
    send = lambda svc, rec: (prod.send("otlp_logs", logs_payload(svc, [rec]).encode()), prod.flush(), time.sleep(0.15))
    run = uuid.uuid4().hex[:6]

    def pre(agent: str, sid: str, cmd: str) -> dict | None:
        return proton_gate.handle({"hook_event_name": "PreToolUse", "session_id": sid, "tool_name": "Bash",
                                   "tool_input": {"command": cmd}}, agent)

    # Claude Code polling loop: 4 identical calls (with varying sleep/description), 5th is blocked once
    sid = f"cc-{run}-loop"
    proton_gate.handle({"hook_event_name": "UserPromptSubmit", "session_id": sid, "prompt": "Wait for deploy #4182"}, "claude-code")
    for i in range(4):
        check(f"claude loop: call {i + 1} allowed", pre("claude-code", sid, "./check_deploy.sh") is None)
        send("claude-code", claude_tool_result(sid, f"sleep {5 * i} && ./check_deploy.sh" if i else "./check_deploy.sh", description=f"poll {i}"))
    v = until_denied(lambda: pre("claude-code", sid, "sleep 10 && ./check_deploy.sh"))
    check("claude loop: 5th call denied with hint", "in a row" in reason(v), reason(v)[:80])
    check("claude loop: same call allowed after one block (applied once)",
          pre("claude-code", sid, "./check_deploy.sh") is None)

    # Codex retry storm: 3 failed shell calls -> next call denied
    sid = f"cx-{run}-flaky"
    for i in range(3):
        pre("codex", sid, "./fetch_metrics.sh")
        send("codex_cli_rs", codex_tool_result(sid, "./fetch_metrics.sh", ok=False))
    v = until_denied(lambda: pre("codex", sid, "./fetch_metrics.sh"))
    check("codex errors: 4th call denied with hint", "failed" in reason(v), reason(v)[:80])

    # Claude Code budget: cost crosses the budget -> PostToolUse stops the session, PreToolUse denies
    sid = f"cc-{run}-budget"
    budget = float(os.environ.get("BUDGET_USD", "0.50"))
    for _ in range(int(budget / 0.12) + 2):
        send("claude-code", claude_api_request(sid, 0.12))
    actions(sid, 1)
    post = proton_gate.handle({"hook_event_name": "PostToolUse", "session_id": sid, "tool_name": "Read",
                               "tool_input": {"file_path": "/workspace/README.md"}}, "claude-code")
    check("claude budget: PostToolUse returns continue:false", bool(post) and post.get("continue") is False)
    v = pre("claude-code", sid, "ls")
    check("claude budget: further tool calls denied", "budget" in reason(v))

    # ...a person resumes it: tool calls run again, and the budget re-arms at 2x
    proton_gate.handle({"hook_event_name": "UserPromptSubmit", "session_id": sid,
                        "prompt": "[resume] the extra spend is approved, carry on"}, "claude-code")
    check("claude budget: [resume] lifts the halt", pre("claude-code", sid, "ls") is None)
    check("claude budget: resume recorded in agent_actions",
          any(a["action"] == "resume" for a in actions(sid, 2)))
    for _ in range(int(budget / 0.12) + 1):
        send("claude-code", claude_api_request(sid, 0.12))
    v = until_denied(lambda: pre("claude-code", sid, "ls"))
    check("claude budget: halts again at 2x the budget", "2x" in reason(v), reason(v)[:90])

    # Codex budget by tokens
    sid = f"cx-{run}-budget"
    tokens = int(os.environ.get("BUDGET_TOKENS", "200000"))
    send("codex_cli_rs", codex_usage(sid, tokens // 2, 1000))
    send("codex_cli_rs", codex_usage(sid, tokens // 2, 1000))
    time.sleep(1.5)
    check("codex budget: halt by tokens", "budget" in detectors(sid, {"budget"}))

    part3_targeting(send, run)

    # the session log the hooks wrote
    rows = q("SELECT event_type FROM table(agent_session_log) WHERE session_id = {s:string}", s=f"cc-{run}-loop")
    check("session log written by hooks", {"user_prompt", "control"} <= {r["event_type"] for r in rows},
          str(sorted({r["event_type"] for r in rows})))


def part3_targeting(send, run: str) -> None:
    print("\n# decisions are aimed at a call, expire, and escalate")

    def pre(sid: str, cmd: str) -> dict | None:
        return proton_gate.handle({"hook_event_name": "PreToolUse", "session_id": sid, "tool_name": "Bash",
                                   "tool_input": {"command": cmd}}, "claude-code")

    def loop(sid: str, cmd: str, n: int = 4) -> None:
        for i in range(n):
            send("claude-code", claude_tool_result(sid, cmd, description=f"try {i}"))

    # the agent already changed course: its next (different) call runs; the old call stays blocked
    sid = f"cc-{run}-moved-on"
    loop(sid, "./check_deploy.sh")
    actions(sid, 1)
    check("moved on: a different call is allowed", pre(sid, "kubectl logs deploy/checkout") is None)
    check("moved on: going back to the looped call is still blocked",
          "in a row" in reason(pre(sid, "sleep 5 && ./check_deploy.sh")))

    # a stale decision does not block a later call
    sid = f"cc-{run}-stale"
    ttl = proton_gate.INTERRUPT_TTL_S
    proton_gate.INTERRUPT_TTL_S = 3
    loop(sid, "./check_deploy.sh")
    actions(sid, 1)
    time.sleep(4.5)
    check("expiry: an interrupt older than its TTL is ignored", pre(sid, "./check_deploy.sh") is None)
    proton_gate.INTERRUPT_TTL_S = ttl

    # an agent that ignores the hint: interrupts at the 4th and 8th identical call, halt at the 12th
    sid = f"cc-{run}-stubborn"
    loop(sid, "./check_deploy.sh", 12)
    got = [a["action"] for a in actions(sid, 3)]
    check("escalation: interrupt, interrupt, then halt", got == ["interrupt", "interrupt", "halt"], str(got))
    v = until_denied(lambda: pre(sid, "cat notes.md"))
    check("escalation: halt blocks any call and says how to resume", "[resume]" in reason(v), reason(v)[-60:])
    proton_gate.handle({"hook_event_name": "UserPromptSubmit", "session_id": sid,
                        "prompt": "[resume] the deploy is fixed now, check it again"}, "claude-code")
    check("resume: calls run again, including the one that looped", pre(sid, "./check_deploy.sh") is None)

    # open loop, then close it (the stage beat): with mv_policy PAUSED, alerts pile up and nothing reaches the
    # agent; RESUME replays the backlog, so every alert that fired while paused becomes a decision at once and
    # the agent's next identical call is denied. Two alerts in the backlog -> two interrupts (a third would
    # escalate to a halt, which is why the runbook says to resume at tool_loop = 2).
    sid = f"cc-{run}-open-closed"
    ddl("SYSTEM PAUSE MATERIALIZED VIEW mv_policy")
    try:
        loop(sid, "./check_deploy.sh", 8)
        check("open loop: alerts fire while mv_policy is paused", alert_count(sid, "tool_loop", 2) == 2)
        check("open loop: no decision, the call is allowed",
              actions(sid, 1, wait_s=2) == [] and pre(sid, "./check_deploy.sh") is None)
    finally:
        ddl("SYSTEM RESUME MATERIALIZED VIEW mv_policy")
    got = [a["action"] for a in actions(sid, 2)]
    check("closed loop: resume replays the backlog into decisions", got == ["interrupt", "interrupt"], str(got))
    v = until_denied(lambda: pre(sid, "./check_deploy.sh"))
    check("closed loop: the next identical call is denied with the hint", "in a row" in reason(v), reason(v)[:80])
    check("closed loop: one denial consumed both replayed interrupts", pre(sid, "./check_deploy.sh") is None)
    loop(sid, "./check_deploy.sh", 12)                       # 12th..20th identical call: still firing (every 4th)
    check("loop detector keeps firing on every 4th identical call", alert_count(sid, "tool_loop", 5) == 5)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kafka", default="localhost:9092")
    ap.add_argument("--otlp", default="http://localhost:4318")
    a = ap.parse_args()
    part1_simulator(a.otlp)
    part2_agent_payloads(a.kafka)
    print("\nall checks passed" if not failures else f"\nFAILED: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
