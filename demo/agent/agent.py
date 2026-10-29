#!/usr/bin/env python3
"""A small ReAct-style agent that can get itself into trouble — and get out of it.

The "LLM" is a deterministic stand-in so the demo runs offline and the same
way every time; everything around it is real: OpenTelemetry GenAI spans, an
append-only session log, and a live subscription to the decisions Proton
makes about this session.

    python agent.py --scenario loop        # repeats the same search until Proton interrupts it
    python agent.py --scenario flaky       # a tool keeps failing; Proton tells it to fall back
    python agent.py --scenario burn        # context balloons; Proton halts it
    python agent.py --scenario normal      # well-behaved; nothing fires
    python agent.py --scenario loop --no-control   # same agent, loop left open
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import uuid
from dataclasses import dataclass, field

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from proton_io import ActionListener, SessionLog
from telemetry import setup_tracing

AGENT_NAME = "research-agent"
MODEL = "mock-llm-1"

# --------------------------------------------------------------------------
# pretty output
# --------------------------------------------------------------------------
USE_COLOR = sys.stdout.isatty() or os.environ.get("FORCE_COLOR")
def c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if USE_COLOR else s
DIM, BOLD, RED, GREEN, YELLOW, CYAN, MAGENTA = "2", "1", "31", "32", "33", "36", "35"


class Clock:
    def __init__(self):
        self.t0 = time.time()

    def stamp(self, t: float | None = None) -> str:
        return c(DIM, f"[{(t or time.time()) - self.t0:6.2f}s]")


# --------------------------------------------------------------------------
# tools (simulated)
# --------------------------------------------------------------------------
class ToolError(Exception):
    def __init__(self, error_type: str, message: str):
        super().__init__(message)
        self.error_type = error_type


def run_tool(scenario: str, name: str, args: dict) -> str:
    time.sleep(random.uniform(0.15, 0.3))
    if name == "search_web":
        if scenario == "loop":
            return "[] (0 results)"
        return json.dumps([{"title": "Proton release notes", "url": "https://github.com/timeplus-io/proton/releases"}])
    if name == "fetch_url":
        if scenario == "flaky":
            raise ToolError("timeout", "upstream did not respond within 5s")
        return "Release notes: streaming joins, Kafka external streams, SQL UDF improvements..."
    if name == "search_docs":
        return "docs: Proton runs streaming SQL over Kafka, OTel, and native streams; see docs.timeplus.com"
    if name == "read_document":
        return "lorem " * 800  # a long chunk, ~1.2k tokens, appended to the context every step
    raise ToolError("unknown_tool", name)


# --------------------------------------------------------------------------
# the stand-in model: a deterministic policy per scenario
# --------------------------------------------------------------------------
@dataclass
class Decision:
    thought: str
    tool: str | None = None
    args: dict = field(default_factory=dict)
    answer: str | None = None


class MockLLM:
    """Plays the part of a model that makes a plausible-but-stuck choice.

    It reads hints injected by the control loop exactly the way a real model
    would read a system message — and changes strategy.
    """

    def __init__(self, scenario: str):
        self.scenario = scenario
        self.step = 0

    def decide(self, context: list[dict]) -> Decision:
        self.step += 1
        hinted = any(m["role"] == "system" and m.get("from") == "control" for m in context)
        tool_results = [m for m in context if m["role"] == "tool"]

        if self.scenario == "normal":
            if not tool_results:
                return Decision("Search for the release notes.", "search_web", {"query": "proton latest release notes"})
            if len(tool_results) == 1:
                return Decision("Open the release page.", "fetch_url", {"url": "https://github.com/timeplus-io/proton/releases"})
            return Decision("I have enough.", answer="Latest release adds streaming joins, Kafka external streams and UDF improvements.")

        if self.scenario == "loop":
            if hinted:
                if not any(m.get("tool") == "search_docs" for m in tool_results):
                    return Decision("Web search is a dead end. Try the project docs instead.", "search_docs", {"query": "benchmark"})
                return Decision("Docs have what I need.", answer="There is no published Q3 2031 benchmark; pointing the user to the docs.")
            return Decision("No results yet — the index may be catching up. Search again.",
                            "search_web", {"query": "proton benchmark Q3 2031"})

        if self.scenario == "flaky":
            if hinted:
                if not any(m.get("tool") == "search_docs" for m in tool_results):
                    return Decision("The page is unreachable. Fall back to the docs.", "search_docs", {"query": "release notes"})
                return Decision("Answer from the docs.", answer="From the docs: the latest release focuses on streaming SQL over Kafka and OTel.")
            return Decision("Fetch the release page (retrying).", "fetch_url", {"url": "https://example.com/releases/latest"})

        if self.scenario == "burn":
            return Decision(f"Read the next section in full before deciding (part {self.step}).",
                            "read_document", {"doc": "proton-architecture.pdf", "part": self.step})

        raise ValueError(self.scenario)


def approx_tokens(context: list[dict]) -> int:
    return sum(len(m["content"]) // 4 for m in context) + 50


# --------------------------------------------------------------------------
# the agent loop
# --------------------------------------------------------------------------
def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scenario", choices=["normal", "loop", "flaky", "burn"], default="loop")
    p.add_argument("--session-id", default=None)
    p.add_argument("--mode", choices=["direct", "collector"], default=os.environ.get("TELEMETRY_MODE", "direct"))
    p.add_argument("--proton-host", default=os.environ.get("PROTON_HOST", "localhost"))
    p.add_argument("--proton-port", type=int, default=int(os.environ.get("PROTON_PORT", "8463")))
    p.add_argument("--proton-http", default=os.environ.get("PROTON_HTTP", "http://localhost:3218"))
    p.add_argument("--otlp-endpoint", default=os.environ.get("OTLP_ENDPOINT", "http://localhost:4318"))
    p.add_argument("--max-steps", type=int, default=30)
    p.add_argument("--no-control", action="store_true", help="ignore Proton's decisions (loop left open)")
    a = p.parse_args()

    session_id = a.session_id or f"{a.scenario}-{uuid.uuid4().hex[:6]}"
    provider = setup_tracing(AGENT_NAME, a.mode, a.proton_http, a.otlp_endpoint)
    tracer = trace.get_tracer("osacon.demo.agent")
    log = SessionLog(a.proton_http, session_id)
    clock = Clock()

    listener = None
    if not a.no_control:
        listener = ActionListener(a.proton_host, a.proton_port, session_id)
        listener.start()
        time.sleep(1.0)  # let the streaming subscription register before we start emitting

    goals = {
        "normal": "Summarize what changed in the latest Proton release.",
        "loop": "Find the Q3 2031 performance benchmark for Proton.",
        "flaky": "Summarize the latest release notes from the project site.",
        "burn": "Read the architecture paper and explain the storage layer.",
    }
    goal = goals[a.scenario]
    print(c(BOLD, f"\nsession {session_id}") + c(DIM, f"  scenario={a.scenario} telemetry={a.mode} control={'off' if a.no_control else 'on'}"))
    print(f"{clock.stamp()} {c(CYAN, 'user')}  {goal}")
    log.append("user_goal", goal)

    llm = MockLLM(a.scenario)
    context: list[dict] = [{"role": "user", "content": goal}]
    calls: list[tuple[str, bool, float]] = []   # (call_key, ok, end_time) for latency reporting
    outcome, exit_code = "max_steps", 1

    common = {"gen_ai.conversation.id": session_id, "gen_ai.agent.name": AGENT_NAME}
    with tracer.start_as_current_span(f"invoke_agent {AGENT_NAME}", attributes={
        **common, "gen_ai.operation.name": "invoke_agent", "gen_ai.request.model": MODEL,
    }) as root:
        for _ in range(a.max_steps):
            # ---- 1. feedback from the stream -------------------------------
            halted = False
            for act in (listener.poll() if listener else []):
                lat = closed_loop_latency(act["reason"], calls, act["received_at"])
                lat_s = f"  ({c(BOLD, f'{lat * 1000:.0f} ms')} after the triggering call)" if lat else ""
                print(f"{clock.stamp(act['received_at'])} {c(MAGENTA, '◀ proton')} {c(BOLD, act['action'])}: {act['reason']}{lat_s}")
                log.append("control", json.dumps(act))
                if act["action"] == "halt":
                    halted = True
                elif act["action"] == "interrupt" and act["hint"]:
                    if not any(m.get("from") == "control" for m in context):
                        context.append({"role": "system", "from": "control", "content": act["hint"]})
                        print(f"{' ' * 9} {c(MAGENTA, '  hint →')} {c(DIM, act['hint'])}")
            if halted:
                outcome, exit_code = "halted", 2
                print(f"{clock.stamp()} {c(RED, '■ halted by policy')}")
                log.append("halted", "halted by policy")
                root.set_status(Status(StatusCode.ERROR, "halted by policy"))
                break

            # ---- 2. model call ---------------------------------------------
            in_tok = approx_tokens(context)
            with tracer.start_as_current_span(f"chat {MODEL}", attributes={
                **common, "gen_ai.operation.name": "chat", "gen_ai.request.model": MODEL,
                "gen_ai.provider.name": "mock",
            }) as span:
                time.sleep(random.uniform(0.3, 0.45))
                d = llm.decide(context)
                out_tok = random.randint(60, 140)
                span.set_attribute("gen_ai.usage.input_tokens", in_tok)
                span.set_attribute("gen_ai.usage.output_tokens", out_tok)
            log.append("llm_decision", d.thought)
            print(f"{clock.stamp()} {c(YELLOW, 'model')} {d.thought} {c(DIM, f'({in_tok:,} in / {out_tok} out tok)')}")

            if d.answer:
                print(f"{clock.stamp()} {c(GREEN, '✔ answer')} {d.answer}")
                log.append("final_answer", d.answer)
                outcome, exit_code = "answered", 0
                break

            # ---- 3. tool call ----------------------------------------------
            args_json = json.dumps(d.args, sort_keys=True)
            key = f"{d.tool}|{args_json}"
            log.append("tool_call", f"{d.tool}({args_json})")
            with tracer.start_as_current_span(f"execute_tool {d.tool}", attributes={
                **common, "gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": d.tool,
                "gen_ai.tool.type": "function", "gen_ai.tool.call.id": uuid.uuid4().hex[:12],
                "gen_ai.tool.call.arguments": args_json,
            }) as span:
                try:
                    result = run_tool(a.scenario, d.tool, d.args)
                    ok = True
                except ToolError as e:
                    result, ok = f"ERROR {e.error_type}: {e}", False
                    span.set_attribute("error.type", e.error_type)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
            calls.append((key, ok, time.time()))
            shown = result if len(result) < 90 else result[:87] + "..."
            print(f"{clock.stamp()} {c(CYAN if ok else RED, 'tool ')} {d.tool}({args_json}) → {c(DIM, shown)}")
            log.append("tool_result", result[:2000])
            context.append({"role": "tool", "tool": d.tool, "content": result})

        root.set_attribute("demo.outcome", outcome)

    provider.force_flush()
    provider.shutdown()
    print(c(BOLD, f"outcome: {outcome}") + c(DIM, f"  ({len(calls)} tool calls, {time.time() - clock.t0:.1f}s)\n"))
    return exit_code


def closed_loop_latency(reason: str, calls: list[tuple[str, bool, float]], received_at: float) -> float | None:
    """Time from the call that completed the bad pattern to the action arriving."""
    now = received_at
    if reason.startswith("tool_loop"):
        for i in range(3, len(calls)):
            if len({k for k, _, _ in calls[i - 3:i + 1]}) == 1:
                return now - calls[i][2]
    if reason.startswith("tool_errors"):
        for i in range(2, len(calls)):
            if not any(ok for _, ok, _ in calls[i - 2:i + 1]):
                return now - calls[i][2]
    return None


if __name__ == "__main__":
    sys.exit(main())
