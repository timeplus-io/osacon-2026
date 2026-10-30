# Handover — state of the demo (2026-10-30)

Talk: **Closing the Loop with Open Source: Streaming SQL from Agent Telemetry to Agent Action**, OSA Con 2026, **Mon Nov 2**, AWS Builder Loft SF. 20 min + 5 Q&A, livestreamed and recorded. The organizers require that it be about open source, not commercial products, and nothing confidential can appear on screen (slides, terminal, `.env`).

Deck (Google Slides): https://docs.google.com/presentation/d/1BJQw398uOurzPfrzBuMDtBnCwht_Q3Zo_JtTvmJarbA/edit
The backup slides "Detect" and "Decide and deliver" show SQL from `demo/sql/03_detectors.sql` and `04_policy.sql`, and the main "The pipeline" slide (data lineage) names every stream and materialized view. **If you change those files, update the slides too** (or tell whoever owns the deck).
**Deck is out of date as of 2026-10-30:** slide 8 must show `lags(call_key, 1, 100)` and `WHERE streak >= 4 AND streak % 4 = 0` (was `1, 12` / `streak IN (4, 8, 12)`).

---

## 1. What the demo does

```
Claude Code / Codex ──OTel log events──▶ Collector ──otlp_json──▶ Kafka:otlp_logs
        ▲                                                              │
        │                                                              ▼
        │                                   Proton: parse → detect → policy → agent_actions
        │                                                              │          │
        └── PreToolUse hook: one lookup, "any decision aimed at this call?" ◀─┘    └─▶ Grafana (humans, optional)
```

- **Detection is asynchronous; enforcement is synchronous and local.** Proton's materialized views write decisions in the background. The hook never waits for them: before each tool call it makes **one lookup** and applies what is already there. A decision therefore takes effect on the agent's *next matching* call, never on the call that triggered it. This is the central design choice; the talk is built around it.
- **Two readers of one stream:** the pink path (agent_actions → hook) is the loop and works with no human. Grafana is for humans and optional.

### Detectors (`sql/03_detectors.sql`), all `PARTITION BY session_id` with `lags()`
| Detector | Fires when | Alert carries |
|---|---|---|
| `tool_loop` | same tool + same normalized target, streak = **4, 8, 12, ...** (every 4th; `lags` window 100) | `tool_name`, `target` |
| `tool_errors` | failed calls in a row, streak = **3, 6, 9** | `tool_name`, `target` |
| `budget` | session spend reaches each **multiple** of `$BUDGET_USD` or `BUDGET_TOKENS` (whichever comes first) | — |

The streak is `array_first_index(x -> x != call_key, lags(call_key, 1, 100))`. Firing on every 4th call (not only 4/8/12) is what makes the open-loop/closed-loop stage beat work: `scripts/policy.sh off|on` drops / recreates `mv_policy`, and a view created late gets its first alert within four calls.

### Policy (`sql/04_policy.sql`)
- `budget` → `halt`
- `tool_loop` / `tool_errors` → `interrupt`, **aimed** at `target`
- the **third** failing pattern in a row in a session (`lags(detector,1,2)`) → `halt` (escalation)
- `hint` = the sentence the model reads as the deny reason.

### Hook (`hooks/proton_gate.py`, stdlib only; used by both agents and the simulator)
- **PreToolUse** makes one HTTP query to Proton (`ACTIONS_SQL`). Proton normalizes the incoming call with the same `agent_call_target()` UDF the detectors use, and returns:
  - halt/resume rows newer than `ack_ms`
  - fresh interrupts (younger than `PROTON_GATE_INTERRUPT_TTL_S`, default 60 s), each with a `matches` flag
- **Interrupt** that matches and isn't consumed → deny **once** (its `t` is recorded in `consumed`). Any other call runs.
- **Halt** → deny every call until resumed. **PostToolUse** returns `{"continue": false, "stopReason": ...}`. `continue:false` lives in PostToolUse because Codex rejects it in PreToolUse.
- **Resume:** a user prompt containing `[resume]` (on UserPromptSubmit) or `scripts/resume.sh <sid>` writes an `action='resume'` row. Halts and pending interrupts from before it are voided.
- **Failure handling:** if Proton is unreachable or slow (`PROTON_GATE_TIMEOUT_S`, 1.5 s), the call is allowed. A halt the hook already knows about still stands.
- **State:** a per-session JSON file in `PROTON_GATE_STATE` (default `~/.cache/proton-gate`) with `ack_ms`, `resume_ms`, `consumed`, `halted`.
- **Matching rule** (in SQL): `target = ''` OR `incoming = ''` OR equal OR substring either way (length ≥ 4). If the hook can't parse the incoming call (`incoming = ''`), it **blocks** (the old, safe behaviour).

**Measured latency** (container, not the laptop): the lookup query takes ~13–15 ms; the hook process end to end takes ~100 ms median, mostly Python start-up. The slides say "one lookup, ~0.1 s". Don't reintroduce "2 ms".

---

## 2. Repo map

```
demo/
  docker-compose.yml        proton, kafka (KRaft), kafka-init, otel-collector, proton-init, grafana;
                            profile "agents": claude, codex, simulator
  .env.example              ANTHROPIC_API_KEY, OPENAI_API_KEY, ANTHROPIC_MODEL, BUDGET_USD=0.50, BUDGET_TOKENS=200000
  sql/01_streams.sql        otlp_logs_raw, agent_events, agent_session_log, agent_alerts, agent_actions
  sql/02_parse_otlp_logs.sql UDFs otel_attrs, agent_call_target; MV OTLP JSON → agent_events (both agents → one schema)
  sql/03_detectors.sql      tool_loop, tool_errors, budget (__BUDGET_USD__/__BUDGET_TOKENS__ substituted by apply-sql.sh)
  sql/04_policy.sql         mv_policy → agent_actions (interrupt/halt, target, hint, escalation)
  sql/05_kafka.sql          Kafka external streams in/out (brokers kafka:9092 substituted by apply-sql.sh)
  sql/99_teardown.sql       drop everything (used by scripts/reset.sh)
  sql/queries.sql           Q1–Q7 for the terminal during the demo
  hooks/proton_gate.py      the hook (see above)
  agents/                   Dockerfile (node:22 + claude-code + codex + python), entrypoint.sh,
                            claude/managed-settings.json (permissions + hooks, timeout 10 s),
                            codex/config.toml ([otel] otlp-http), codex/hooks.json
  simulator/simulator.py    scripted agent: emits the same OTel events, calls proton_gate.handle()
  fakes/ops_api.py          stdlib HTTP stand-in for the deploy service (always IN_PROGRESS, counters move)
                            and the metrics API (always 503 "retry"); compose service ops-api, aliases
                            deploy-api and metrics.internal. NOT in /workspace: agents can't read it.
  workspace/                check_deploy.sh and fetch_metrics.sh are thin curl clients of ops-api;
                            metrics-cache/, postmortems/ (fictional)
  grafana/provisioning/     Proton datasource + dashboard "closing-the-loop"
  scripts/apply-sql.sh      apply schema (idempotent); reset.sh (teardown + reapply); resume.sh;
                            policy.sh off|on (drop / recreate mv_policy: open or close the loop on stage)
  tests/e2e_test.py         25 checks through Kafka; mini_collector.py (OTLP → Kafka stand-in); otlp_fixtures.py
docs/architecture.md        architecture, schema mapping, "How a decision reaches the agent", recovery
talk/                       abstract, outline (timings, notes, Q&A), demo-runbook (the one on-stage demo: Claude Code
                            polling, open loop -> close it), demo-runbook-extras (Codex retry storm, post-mortem,
                            budget halt: Q&A / hallway only), checklist, assets (icons, logos)
```

---

## 3. Running it

### Full stack (presenting laptop)
```bash
cd demo && cp .env.example .env     # add keys; BUDGET_USD=0.15 if you'll show the budget halt
docker compose build && docker compose up -d
docker compose run --rm claude      # or: codex | simulator --scenario loop|flaky|burn|normal
scripts/reset.sh                    # clean slate right before going on stage
```
Grafana: http://localhost:3000 (anonymous admin). Demo prompts are in `talk/demo-runbook.md`.

### Fast test loop without Docker (how everything so far was verified)
```bash
# Proton binary from github.com/timeplus-io/proton releases (v3.0.31 used); run in an empty dir
proton server &
# any Kafka on localhost:9092 (a real broker, or a single-binary fake such as franz-go's kfake)
python3 demo/tests/mini_collector.py --port 4318 --brokers localhost:9092 &
PROTON_BIN=proton PROTON_HOST=localhost KAFKA_BROKERS=localhost:9092 bash demo/scripts/apply-sql.sh
pip install -r demo/tests/requirements.txt -r demo/simulator/requirements.txt opentelemetry-proto protobuf
python3 demo/tests/e2e_test.py --kafka localhost:9092 --otlp http://localhost:4318
```
After changing SQL: `proton client --host localhost --multiquery < demo/sql/99_teardown.sql`, then apply again.

Proton gotchas we hit:
- Rows written by an MV take a moment to show up in `table(...)` reads, so the tests poll (`actions()`, `until_denied()`).
- An alias can't shadow a column it uses (hence `alert_target` in the policy).
- UDF names can't end in `_map`.
- `date_diff_within` joins only worked up to ~2m.
- A `lags()` bool column pads with `false`; use a `uint8` flag instead.
- Time windows over many sessions share one watermark (an alert waited for other sessions' events, then fired 9×). That's why detectors use per-session row state.

---

## 4. Verified vs. NOT verified

**Verified (local Proton + fake Kafka + mini collector):** all 25 e2e checks, covering:
- simulator scenarios
- Claude Code / Codex-shaped OTLP payloads
- loop → 5th call denied, then the same call allowed
- Codex error streak
- budget halt, `[resume]`, re-halt at 2×
- Codex token budget
- moved on → different call allowed, looped call still blocked
- TTL expiry
- escalation: interrupt, interrupt, halt
- resume after escalation
- session log

**NOT verified yet. Do these first:**
1. **Bring the real containers up:** `apache/kafka`, the contrib Collector, Grafana with the Proton plugin, and the agents image.
2. **A live Claude Code session** with the polling-loop prompt: does the 5th check get denied and does Claude report the deploy as stuck?
3. **A live Codex session.** Two unknowns:
   - (a) the exact `tool_name`/`tool_input` shape Codex sends to PreToolUse hooks. Matching falls back to "block" if it can't parse, but check that the target actually matches.
   - (b) whether Codex keeps retrying or goes straight to `metrics-cache/` (both are fine; see demo-runbook-extras).
4. **Grafana plugin architecture:** the Proton datasource v2.1.5 zip ships **arm64-only** Linux binaries. That's fine on Apple silicon. On x86, build it from source or use terminal queries.
5. **`[resume]` in a real session:** confirm Claude Code and Codex both fire UserPromptSubmit after a `continue:false` stop, in the same session.
6. **Hook timeout behaviour with Proton stopped mid-session:** we expect Claude Code to treat it as non-blocking, and believe Codex does the same.
7. **Timing:** run the demo end to end against the clock. Only the Claude Code polling demo is on stage (target 4 min, open loop -> close it live); Codex, post-mortem and budget are extras. The simulator is the fallback; use the live agent if it reliably triggers in rehearsal.

---

### Findings from the first live Claude Code run (2026-10-30, Opus 5.5)
- The model read `check_deploy.sh`, saw the hardcoded "never finishes" demo script, and refused to poll. Fixed: the scripts are now thin clients of the `ops-api` container (`fakes/ops_api.py`), which the agent can't read.
- Asked to check "about every 10 seconds", it wrote **one** `while true; do ./check_deploy.sh; sleep 10; done` Bash call with `run_in_background: true` and answered immediately. One tool call, so `tool_loop` can't fire. Fixes: the prompt now says "run each check as its own command, not a loop or a background job", and managed settings set `permissions.defaultMode = "default"` so a command outside the allowlist prompts the presenter (the session had started in `auto` mode, which accepted the loop). Decline the prompt and the model falls back to single calls. Re-verify.
- The dashboard's "live" tables ran plain streaming queries; with `refresh: 5s` every refresh restarted the query and the rows vanished ("tool calls show, then gone"). **The dashboard now has no auto-refresh and every panel is a streaming query.** The Proton datasource plugin (v2.1.5) asks Proton's analyzer whether the SQL is streaming and, if so, returns a Grafana Live channel; the backend pushes new rows as frames and Grafana appends them (`StreamingFrameAction.Append`, buffer = panel `maxDataPoints`, trimmed to the time range). A dashboard refresh re-runs the query and gets a new channel, which is what wiped the rows. Live tables use `SETTINGS seek_to='-15m'` so a freshly opened dashboard replays history; the two former `table()` panels are streaming aggregations with `EMIT PERIODIC 2s SETTINGS seek_to='-1h'` (Alerts: running totals in a bar gauge with reducer *last*; Sessions: `GROUP BY session_id` plus a Grafana *Group by -> last* transformation, since every re-emitted row is appended). Verified in a browser: rows from a new simulator run appeared in all panels with no refresh.
- **The presenting laptop's own Claude Code exports to `localhost:4318`** (`~/.claude/settings.json` sets `OTEL_EXPORTER_OTLP_ENDPOINT`), so every local session lands in the demo streams and in Grafana; the budget policy halted the dev session twice. Before going on stage, disable that or point it elsewhere, then `scripts/reset.sh`.

## 5. Open ideas (not started)

- **Pipeline-health panel:** time since the last `agent_events` row, so a silently broken pipeline is visible. Optionally a watchdog MV.
- **`PROTON_GATE_MODE=closed`:** deny calls when Proton is unreachable, for strict environments.
- **Scaling:** keep only the latest decision per session (a keyed store) or put a TTL on `agent_actions`, so the lookup stays constant-time.
- **Grafana:** show `resume` rows and the escalation in the *Decisions* panel. Rows already flow; panel styling is untouched.

## 6. Conventions

- Keep all infrastructure open source. On slides, the agents appear by name only, never their logos; project logos are fine (sources and trademarks are listed in `talk/assets/logos/README.md`).
- The hook stays stdlib-only Python. Agent configs install it from `/opt/demo/hooks/proton_gate.py`.
- Any behaviour change needs an e2e check in `tests/e2e_test.py`.
