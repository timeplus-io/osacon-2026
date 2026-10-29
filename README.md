# Closing the Loop with Open Source

**Streaming SQL from Agent Telemetry to Agent Action** — talk and demo for [OSA Con 2026](https://luma.com/eis7567t), November 2, 2026, San Francisco.

AI agents produce telemetry that is larger, longer, and branchier than anything a request/response system emits — and they are the first systems that can act on it themselves. This repo closes that loop with open source: OpenTelemetry for the signal, an append-only stream as the agent's session log, and [Proton](https://github.com/timeplus-io/proton)'s streaming SQL to detect tool-call loops, retry storms, and runaway token use in well under a second, then feed the decision back to the running agent.

```
agent ──OTel spans──▶ Collector ──▶ Kafka ──▶ Proton: parse → detect → policy
  ▲                                                                   │
  └──────────────── live streaming query: interrupt / halt ◀──────────┘
```

## Quick start

```bash
cd demo
docker compose up -d
docker compose run --rm agent --scenario loop
```

No Docker? Run it with just the Proton binary — see [`demo/README.md`](demo/README.md#option-b--just-the-proton-binary-no-docker-no-kafka).

## What's here

| Path | Contents |
|---|---|
| [`talk/abstract.md`](talk/abstract.md) | Title, abstract (long + short), components and licenses |
| [`talk/outline.md`](talk/outline.md) | 13-slide outline with timing and speaker notes, likely Q&A |
| [`talk/demo-runbook.md`](talk/demo-runbook.md) | Step-by-step on-stage demo with fallbacks |
| [`talk/checklist.md`](talk/checklist.md) | Speaker prep checklist |
| [`docs/architecture.md`](docs/architecture.md) | Architecture diagram, data flow, detector design notes |
| [`demo/`](demo/) | Runnable demo: docker-compose stack, SQL, agent, tests |

## Components (all open source)

- [OpenTelemetry](https://opentelemetry.io) SDK + Collector — Apache 2.0
- [Apache Kafka](https://kafka.apache.org) — Apache 2.0
- [Proton](https://github.com/timeplus-io/proton) — Apache 2.0
- [proton-driver](https://github.com/timeplus-io/proton-python-driver) — MIT
