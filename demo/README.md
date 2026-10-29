# Demo: closing the loop on Claude Code and Codex

A real coding agent (Claude Code or Codex) works in a small ops workspace. It exports its activity as OpenTelemetry log events; the Collector puts them on Kafka; Proton detects a polling loop, a retry storm, or a blown budget with streaming SQL; and the agent's own `PreToolUse` hook reads the decision before its next tool call — blocking the call and telling the model why. The model reads that like any tool result and changes course. Grafana shows it live.

Everything runs in one `docker compose` stack. All infrastructure is open source; the agents are the clients being observed.

See [`../docs/architecture.md`](../docs/architecture.md) for the diagram and design notes.

## Setup (once)

```bash
cd demo
cp .env.example .env          # add ANTHROPIC_API_KEY and/or OPENAI_API_KEY
docker compose build          # agents image: Claude Code + Codex + hooks
docker compose up -d          # proton, kafka, otel-collector, grafana, schema
```

Open Grafana at **http://localhost:3000** (no login) — the *Closing the Loop* dashboard is the home page.

## Run an agent

```bash
docker compose run --rm claude      # Claude Code, in /workspace
docker compose run --rm codex       # Codex, in /workspace
```

Then give it one of these tasks:

| Scenario | Prompt | What happens |
|---|---|---|
| **Polling loop** | `Deploy #4182 is rolling out. Keep checking it with ./check_deploy.sh until it finishes, then tell me the result.` | The deploy never finishes. After 4 identical checks Proton fires `tool_loop`; the 5th check is blocked with a hint and the agent reports the deploy as stuck. |
| **Retry storm** | `Pull the last hour of error-rate metrics with ./fetch_metrics.sh and summarize them.` | The metrics API is down. After 3 failures Proton fires `tool_errors`; the next retry is blocked and the agent falls back to `metrics-cache/`. |
| **Budget** | `Read every postmortem in postmortems/ and write a summary of recurring root causes to SUMMARY.md.` | Reading everything is expensive. When session spend crosses `BUDGET_USD` (Claude Code) or `BUDGET_TOKENS` (Codex), Proton fires `budget`; the hook stops the session. Set `BUDGET_USD=0.15` in `.env` and run `scripts/reset.sh` to make this happen within a minute. |

Real models don't misbehave on cue every time — that's the point of the next section.

## No API key / no network: the simulator

```bash
docker compose run --rm simulator --scenario loop     # also: flaky, burn, normal
docker compose run --rm simulator --scenario loop --no-control   # same agent, nobody listening
```

The simulator is a scripted stand-in that emits the same OpenTelemetry events as Claude Code and calls the same hook at the same points, so everything downstream — Kafka, Proton, detectors, policy, gate, Grafana — is exercised exactly as with a real agent. Use it to rehearse, as a stage fallback, and in tests.

## Watch it in SQL

```bash
docker compose exec proton proton client
```

`sql/queries.sql` has the live queries (tool calls, spend per session, decisions, alert ↔ prompt join, session replay, post-mortem by agent).

## Layout

```
demo/
├── docker-compose.yml          the whole stack
├── .env.example                API keys, budgets
├── otel-collector/config.yaml  OTLP in → Kafka (otlp_json) out
├── sql/
│   ├── 01_streams.sql          streams
│   ├── 02_parse_otlp_logs.sql  OTLP/JSON logs → agent_events (Claude Code + Codex vocabularies)
│   ├── 03_detectors.sql        tool_loop, tool_errors, budget
│   ├── 04_policy.sql           alerts → interrupt / halt, with the hint text
│   ├── 05_kafka.sql            Kafka in (otlp_logs) and out (agent_actions)
│   ├── queries.sql             live queries for the terminal
│   └── 99_teardown.sql
├── hooks/proton_gate.py        the hook both agents call (stdlib Python)
├── agents/                     agents image: Dockerfile, Claude Code managed settings, Codex config + hooks
├── workspace/                  what the agent works on: check_deploy.sh, fetch_metrics.sh, metrics-cache/, postmortems/
├── simulator/                  offline stand-in agent
├── grafana/provisioning/       Proton data source + dashboard
├── scripts/                    apply-sql.sh, reset.sh
└── tests/                      e2e_test.py, mini_collector.py, otlp_fixtures.py
```

## How each agent is wired

| | Claude Code | Codex |
|---|---|---|
| Telemetry | env: `CLAUDE_CODE_ENABLE_TELEMETRY=1`, `OTEL_LOGS_EXPORTER=otlp`, `OTEL_LOG_TOOL_DETAILS=1`, `OTEL_LOGS_EXPORT_INTERVAL=500` (in `docker-compose.yml`) | `[otel]` exporter `otlp-http` in `/etc/codex/config.toml` |
| Events used | `claude_code.tool_result`, `claude_code.api_request` | `codex.tool_result`, `codex.sse_event` |
| Session id | `session.id` (same id the hooks receive) | `conversation.id` (same id the hooks receive) |
| Hooks | `/etc/claude-code/managed-settings.json` | `/etc/codex/hooks.json` (system layer, so trusted) |
| Interrupt | `PreToolUse` → `permissionDecision: deny` + reason | same |
| Halt | `PostToolUse` → `continue: false`; `PreToolUse` → deny | same |

## Tests

The e2e test needs Proton, a Kafka broker, and an OTLP endpoint writing to the `otlp_logs` topic. With the stack up:

```bash
pip install -r simulator/requirements.txt -r tests/requirements.txt
python tests/e2e_test.py --kafka localhost:19092 --otlp http://localhost:4318
```

It runs the four simulator scenarios end to end, then replays Claude Code- and Codex-shaped OTLP events through Kafka and drives `proton_gate.py` with each agent's hook payloads, checking that calls are allowed, blocked, or stopped at the right moment.

### What has been verified, and what hasn't

- **Verified** (Proton v3.0.31, Kafka protocol, OTLP/HTTP → Kafka shim in place of the Collector): every SQL file; all four simulator scenarios; Claude Code- and Codex-shaped payloads (attribute names taken from Claude Code 2.1.312 and the open-source Codex code) through parser → detectors → policy → hook; the hook's fail-open behavior; every query in `queries.sql`; every Grafana panel query.
- **Not yet run**: the containers themselves — the Collector, `apache/kafka`, Grafana with the Proton plugin, and the agents image — and live Claude Code / Codex sessions. Run the setup above once on the presenting laptop.
- **Grafana plugin note**: the Proton data source v2.1.5 is unsigned (allowed via `GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS`) and its release zip ships Linux binaries for **arm64 only** — fine on an Apple-silicon Mac; on an x86 host build the plugin from source or use the terminal queries.
