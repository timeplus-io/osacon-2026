# Demo: closing the loop on a misbehaving agent

An agent emits OpenTelemetry spans; Proton detects a tool-call loop, a retry storm, or runaway token use with streaming SQL; the decision goes straight back to the running agent, which changes course or stops. All open source, runs offline.

See [`../docs/architecture.md`](../docs/architecture.md) for the diagram and design notes.

```
demo/
├── docker-compose.yml        proton + kafka + otel-collector + schema init + agent
├── otel-collector/config.yaml  OTLP in → Kafka out (otlp_json)
├── sql/
│   ├── 01_streams.sql        streams
│   ├── 02_parse_otlp.sql     OTLP/JSON → one row per span
│   ├── 03_detectors.sql      tool_loop, tool_errors, token_burn
│   ├── 04_policy.sql         alerts → interrupt / halt
│   ├── 05_kafka.sql          Kafka in/out (compose stack only)
│   ├── queries.sql           what to run live
│   └── 99_teardown.sql
├── agent/                    the agent (Python, OTel SDK, proton-driver)
├── scripts/                  setup.sh, reset.sh
└── tests/                    e2e_test.py, mini_collector.py
```

## Option A — Docker Compose (the full path)

```bash
cd demo
docker compose up -d                              # proton, kafka, otel-collector, schema
docker compose run --rm agent --scenario loop
```

In another terminal, watch decisions as they happen:

```bash
docker compose exec proton proton client
```
```sql
SELECT _tp_time, session_id, action, reason FROM agent_actions;
```

## Option B — just the Proton binary (no Docker, no Kafka)

The agent posts OTLP/JSON straight to Proton's HTTP ingest API; everything downstream is identical.

```bash
# 1. Proton: download the binary for your OS from
#    https://github.com/timeplus-io/proton/releases, then
./proton server                                   # leave running

# 2. schema
PROTON_BIN=./proton demo/scripts/setup.sh

# 3. agent
pip install -r demo/agent/requirements.txt
python demo/agent/agent.py --scenario loop        # --mode direct is the default
```

## Scenarios

| Scenario | What the agent does | What Proton does | Outcome |
|---|---|---|---|
| `normal` | search → fetch → answer | nothing fires | answers |
| `loop` | repeats the same empty search | `tool_loop` → **interrupt** with a hint | switches to the docs, answers |
| `flaky` | retries a URL that keeps timing out | `tool_errors` → **interrupt** with a hint | falls back, answers |
| `burn` | re-reads ever-larger context each step | `token_burn` → **halt** | stopped |

Add `--no-control` to any scenario to run the same agent without listening to Proton (the alerts still appear in `agent_alerts`; the agent just never hears them).

Typical output for `loop`:

```
session loop-79aa22  scenario=loop telemetry=direct control=on
[  1.00s] user  Find the Q3 2031 performance benchmark for Proton.
[  1.39s] model No results yet — the index may be catching up. Search again. (62 in / 89 out tok)
[  1.61s] tool  search_web({"query": "proton benchmark Q3 2031"}) → [] (0 results)
   ... three more identical calls ...
[  3.76s] ◀ proton interrupt: tool_loop: search_web called 4x in a row with identical arguments  (262 ms after the triggering call)
            hint → You have called search_web(...) four times with the same result. ... Change strategy ...
[  4.66s] model Web search is a dead end. Try the project docs instead.
[  4.88s] tool  search_docs({"query": "benchmark"}) → docs: ...
[  5.23s] ✔ answer There is no published Q3 2031 benchmark; pointing the user to the docs.
outcome: answered  (6 tool calls, 5.2s)
```

## About the agent

The "LLM" is a deterministic stand-in (`MockLLM` in `agent/agent.py`) so the demo is reproducible and needs no API key or network. Everything else is real: OTel spans with GenAI semantic conventions, the session log, Kafka transport, Proton detection, and the live subscription that feeds decisions back. To use a real model, replace `MockLLM.decide()`; the telemetry and control path don't change.

## Tests

```bash
# Proton running locally with the schema applied (Option B):
python demo/tests/e2e_test.py                      # direct mode

# Kafka path without Docker: a broker on localhost:9092, then
KAFKA_BROKERS=localhost:9092 demo/scripts/setup.sh --kafka
pip install -r demo/tests/requirements.txt
python demo/tests/mini_collector.py &              # stands in for the OTel Collector
python demo/tests/e2e_test.py --mode collector
```

`e2e_test.py` runs all four scenarios and checks the exit code, which detectors fired, that an action reached the agent, and that spans and session-log rows landed.

### What has been verified

- Proton v3.0.31 (Linux x86_64 binary): every SQL file, every query in `queries.sql`.
- Both ingest paths, all four scenarios passing: direct HTTP ingest, and OTLP/HTTP → `mini_collector.py` → Kafka-protocol broker → Proton external stream → detectors → agent, with actions republished to Kafka.
- Not yet run in this exact form: the docker-compose stack itself (the OTel Collector container and the `apache/kafka` container). Run `docker compose up -d && docker compose run --rm agent --scenario loop` once on the presenting laptop before the talk.
