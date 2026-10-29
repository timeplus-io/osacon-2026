# Closing the Loop with Open Source: Streaming SQL from Agent Telemetry to Agent Action

**Speaker:** Gang Tao, Timeplus
**Event:** OSA Con 2026 — November 2, 2026, AWS Builder Loft, San Francisco
**Format:** 20-minute talk + 5 minutes Q&A, live demo with Claude Code and Codex
**Track fit:** open source analytics × AI agents; real-time analytics

---

## Abstract

AI agents generate telemetry that looks nothing like a web request: traces that branch across tool calls, model invocations, and retrieval hops, run for minutes instead of milliseconds, and arrive in volumes several times larger than the services they replace. Most teams still treat this data as something to inspect after the fact. But agents are the first systems that can act on their own telemetry, and "observe later" is too slow once the system is making decisions on its own.

This talk shows how to close that loop end to end with open source. OpenTelemetry provides the signal; an append-only event stream serves as the agent's own session log; and Proton, an open-source streaming SQL engine derived from ClickHouse, runs stateful queries over both to detect tool-call loops, runaway cost, and behavioral drift in seconds, then feeds those decisions back to the agent. We'll walk through the architecture, run a live demo of an agent being caught mid-loop, and share the patterns that held up in production, the ones that didn't, and the open problems that remain, including how to run the entire loop with no outbound network access.

Attendees will leave with a reference architecture built entirely on open-source components and the SQL to reproduce it.

## Short version (schedule listing, ~55 words)

AI agents produce telemetry that is larger, longer, and branchier than anything a request/response system emits, and they can act on it themselves. This talk closes that loop with open source: OpenTelemetry for the signal, an append-only stream as the agent's session log, and Proton's streaming SQL to detect loops, cost spikes, and drift in seconds and feed decisions back to the agent. Live demo included.

## What's on screen

| Component | Role | License |
|---|---|---|
| [OpenTelemetry](https://opentelemetry.io) Collector | Agent log events → Kafka (OTLP/JSON) | Apache 2.0 |
| [Apache Kafka](https://kafka.apache.org) (KRaft, single node) | Bridge for events in and decisions out | Apache 2.0 |
| [Proton](https://github.com/timeplus-io/proton) | Streaming SQL: parse, detect, decide | Apache 2.0 |
| [Grafana](https://github.com/grafana/grafana) + [Proton data source](https://github.com/timeplus-io/proton-grafana-source) | Live dashboard | AGPL-3.0 / Apache 2.0 |
| [Codex CLI](https://github.com/openai/codex) | Agent being observed | Apache 2.0 |
| [Claude Code](https://github.com/anthropics/claude-code) | Agent being observed | proprietary (client only) |

The agents are the clients being observed; the loop works for any agent that exports OpenTelemetry and supports pre-tool-call hooks.
