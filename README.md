# Closing the Loop with Open Source

**Streaming SQL from Agent Telemetry to Agent Action** — talk and demo for [OSA Con 2026](https://luma.com/eis7567t), November 2, 2026, San Francisco.

Coding agents like Claude Code and Codex already export OpenTelemetry for every tool call and model call — and they are the first systems that can act on that signal themselves. This repo closes the loop with open source: the OpenTelemetry Collector puts agent events on Kafka, [Proton](https://github.com/timeplus-io/proton) detects polling loops, retry storms, and blown budgets with streaming SQL, and the agent's own pre-tool-call hook reads the decision and puts it in front of the model before its next step. Grafana shows it live.

```
Claude Code / Codex ──OTel log events──▶ Collector ──▶ Kafka ──▶ Proton: parse → detect → policy
        ▲                                                                       │
        └──────────── PreToolUse hook: "blocked — here's why" ◀─────────────────┘
```

## Quick start

```bash
cd demo
cp .env.example .env            # add ANTHROPIC_API_KEY and/or OPENAI_API_KEY
docker compose build && docker compose up -d
docker compose run --rm claude  # or: codex
# no API key? docker compose run --rm simulator --scenario loop
```

Grafana: http://localhost:3000. Details and demo prompts: [`demo/README.md`](demo/README.md).

## What's here

| Path | Contents |
|---|---|
| [`talk/abstract.md`](talk/abstract.md) | Title, abstract (long + short), components and licenses |
| [`talk/outline.md`](talk/outline.md) | 13-slide outline with timing, speaker notes, likely Q&A |
| [`talk/demo-runbook.md`](talk/demo-runbook.md) | On-stage demo with Claude Code and Codex, prompts, fallbacks |
| [`talk/checklist.md`](talk/checklist.md) | Speaker prep checklist |
| [`docs/architecture.md`](docs/architecture.md) | Architecture, how both agents map to one schema, design notes |
| [`demo/`](demo/) | The whole demo as one docker-compose stack |

## Components

Infrastructure (all open source): [OpenTelemetry Collector](https://opentelemetry.io) · [Apache Kafka](https://kafka.apache.org) · [Proton](https://github.com/timeplus-io/proton) · [Grafana](https://github.com/grafana/grafana) with the [Proton data source](https://github.com/timeplus-io/proton-grafana-source).
Agents observed: [Codex CLI](https://github.com/openai/codex) (Apache-2.0), [Claude Code](https://github.com/anthropics/claude-code), and a scripted offline simulator.
