# Talk outline and speaker notes

**Closing the Loop with Open Source: Streaming SQL from Agent Telemetry to Agent Action**
20 minutes + 5 minutes Q&A · 11 main slides + 4 backup · ~6 minutes of live demo (simulator by default; live Claude Code/Codex if rehearsals are reliable)

Ground rules for this venue (from the organizers): open source only, no commercial content, the room is livestreamed and recorded. The infrastructure on screen is all OSS (OpenTelemetry, Kafka, Proton, Grafana). The agents are the *clients* being observed — Codex is open source (Apache-2.0); Claude Code is not, so say once that the loop works the same for any agent that exports OTel and has hooks. No customer names; nothing confidential on slides, terminals, or in `.env`.

---

## Timing at a glance

| # | Slide | Time | Cumulative |
|---|---|---|---|
| 1 | Title | 0:30 | 0:30 |
| 2 | Agents can act on their own telemetry | 1:00 | 1:30 |
| 3 | What coding agents already emit | 1:30 | 3:00 |
| 4 | Three failures that burn money in seconds | 1:30 | 4:30 |
| 5 | The loop (architecture; Kafka bridge + one-schema view in one line) | 2:00 | 6:30 |
| 6 | A detector is a materialized view | 2:00 | 8:30 |
| 7 | The policy is SQL; the hook delivers it | 2:00 | 10:30 |
| 8 | **Live demo** | 6:00 | 16:30 |
| 9 | What held up, what didn't, what's still open | 2:00 | 18:30 |
| 10 | Takeaway | 0:45 | 19:15 |
| 11 | Run it yourself (QR) | 0:30 | 19:45 |
| — | *Backup: divider, configuration, parse view, open problems* | Q&A only | |

Cut from the main flow to fit 20 minutes: the configuration slide and the parse-SQL slide (one sentence each on the architecture slide now), and the standalone open-problems slide (now a one-line "still open" strip on the lessons slide). All three are in the backup section for Q&A.

If the demo runs long, drop the "still open" strip to one sentence. If a live agent doesn't cooperate, switch to the simulator (same pipeline) — see `demo-runbook.md`. Don't debug on stage.

The per-slide notes below keep the original numbering (1–13); the deck order is above.

---

## 1. Title (0:30)

**On screen:** title, name, repo URL `github.com/timeplus-io/osacon-2026`.

> I work on Proton, an open-source streaming SQL engine. Today is about a loop every team running coding agents will need, built from open parts. Everything I show is in that repo — one `docker compose up`.

## 2. Agents are the first systems that can act on their own telemetry (1:00)

**On screen:** illustration (dashboard-only vs. closed loop) + *"The same stream can feed two readers: a dashboard for humans, and a hook that hands decisions back to the agent."*

> For twenty years telemetry has been for humans: dashboards, alerts, someone looks during an incident. Agents produce far more of it — every step is a model call or a tool call — and they're the first systems that can read a signal about themselves and change course. So the same stream gets a second reader: the agent itself. The dashboard stays, for us; the loop doesn't need it.

## 3. What coding agents already emit (1:30)

**On screen:** two real OTel log events side by side — `claude_code.tool_result` (`session.id`, `tool_name`, `success`, `duration_ms`, `tool_input`) and `codex.tool_result` (`conversation.id`, `tool_name`, `success`, `arguments`); below them `api_request` / `sse_event` with tokens and cost.

> Claude Code and Codex both already export OpenTelemetry — log events for every tool call and every model call, with tokens, cost, success, and the arguments. You turn it on with a few environment variables. Different names for the same things — we'll deal with that in one SQL view. The point: the signal exists today; nobody has to instrument anything.

## 4. Failures that happen in seconds (1:15)

**On screen:** three cards — **Polling loop** (waits for something that never finishes) · **Retry storm** (a dependency is down; the agent hammers it) · **Runaway spend** (re-reads everything, every step).

> If you've run coding agents you've seen all three. By the time a human looks at a dashboard, the agent has made dozens of calls and spent real money. An agent loops every few seconds; a five-minute alert is a very long time.

## 5. The loop (0:45)

**On screen:** agent → OTel Collector → Kafka → Proton (parse → detect → policy), then two branches: **pink** `agent_actions` → PreToolUse hook → back into the agent ("for the agent: the loop"), and **gray** Grafana ("for humans: optional").

> Signal goes out over standard OpenTelemetry. Kafka carries it. Proton turns it into decisions with streaming SQL. The decision comes back through the agent's own hook — before its next tool call. Nothing custom in the middle, nothing patched in the agent. Two readers of the same stream: the pink branch is the loop, the gray one is Grafana for us — optional; delete it and the loop still works.

## 6. Signal: OTel → Collector → Kafka (1:15)

**On screen:** the Claude Code env vars (5 lines), the Codex `[otel]` block (3 lines), the Collector's `kafka` exporter with `encoding: otlp_json`.

> Turning it on is configuration. The Collector writes OTLP/JSON to a Kafka topic. Why Kafka? Proton doesn't speak OTLP — and it shouldn't have to: Kafka is the bridge everyone already runs, and it's where the decisions fan back out too.

## 7. Engine: Proton — two vocabularies, one schema (1:30)

**On screen:** *Proton: Apache 2.0, single binary, ClickHouse-derived, streaming + historical SQL.* Then the heart of `sql/02_parse_otlp_logs.sql`: the `array_join` over `resourceLogs → scopeLogs → logRecords`, the `if(attrs['session.id'] != '', …, attrs['conversation.id'])` mapping, and `agent_call_target()` stripping `sleep N &&`.

> One materialized view reads the topic, flattens OTLP, and maps both agents onto one schema. Detail that matters: agents rewrite the free-text bits of a tool call every time — a different description, a different sleep — so we compare the *target*, not the raw arguments. Otherwise you'll never see the loop.

## 8. A detector is a materialized view (1:30)

**On screen:** `sql/03_detectors.sql`, D1. Highlight `PARTITION BY session_id` and `lags(call_key, 1, 4)`.

> This is the loop detector, the whole thing. `PARTITION BY session_id` gives every session its own state. `lags` looks at that session's last four tool calls. Same tool, same target, four times in a row: fire, once. It runs forever; nobody schedules it; it doesn't care which agent it's watching.

## 9. The policy is SQL; the hook delivers it (1:15)

**On screen:** left — `sql/04_policy.sql` (`multi_if` detector → `interrupt`/`halt` + hint text). Right — the hook's output: `{"permissionDecision": "deny", "permissionDecisionReason": "[stream policy] You have repeated the same tool call four times…"}`.

> Alerts become actions with one more view, and the policy is reviewable SQL. Delivery: both Claude Code and Codex call a PreToolUse hook before every tool call. Ours asks Proton "anything for this session?" — a 2-millisecond query. If there's an interrupt, the call is denied and the reason is our hint. The model reads it like any tool result and changes course. Halt stops the session.

## 10. Live demo (5:00)

Follow `demo-runbook.md`. Grafana on one half of the screen, the agent terminal on the other.

1. **Polling loop — Claude Code** (~2 min). Prompt: wait for deploy #4182. The agent checks, sleeps, checks… On the 4th identical check a row appears in *Decisions*; the 5th check is blocked and Claude Code prints the hook's reason; it tells you the deploy looks stuck. *"Nobody wrote a rule inside Claude Code. The stream decided; the hook delivered."*
2. **Retry storm — Codex** (~1.5 min). Prompt: pull metrics with `./fetch_metrics.sh`. Three failures → the next retry is blocked → Codex falls back to `metrics-cache/`. *"Different agent, different telemetry vocabulary, same SQL."*
3. **Post-mortem** (~30s). Grafana *Alerts by detector* / terminal Q6: same engine, now a historical question across both agents.

Budget halt: show only if time allows (set `BUDGET_USD=0.15` beforehand), otherwise mention it.

## 11. What held up, what didn't (2:30)

**Held up**
- Per-session state (`PARTITION BY`) instead of global windows.
- Fire once, on the crossing. Detectors that fire every second are noise; models and humans both stop listening.
- Compare the normalized target, not raw arguments.
- Interrupt before halt. A one-sentence hint usually fixes a loop; save halt for budgets.
- Deliver through the agent's own hook — no fork, no wrapper, works for any agent with hooks.
- Policy in SQL, versioned with the code.

**Didn't**
- Time windows for per-session detection: the watermark is shared across sessions, so one session's alert waited for another's events, then fired nine times. (Real, from building this demo.)
- Exact-match on tool arguments: the agent's `description` changes every call, so the loop was invisible.
- Detecting inside the agent: it's the thing that's broken.

## 12. Open problems (1:15)

- **Semantic loops** — same intent, different commands. Needs embeddings in the pipeline; costs latency.
- **Between tool calls** — the hook acts at the next tool call; a model that's only "thinking" can't be interrupted that way.
- **Multi-agent causality** — when agent A's output loops agent B, the pattern spans sessions.
- **Sensitive content** — tool arguments and prompts in telemetry are a governance problem (`OTEL_LOG_TOOL_DETAILS` is off by default for a reason).
- **Fully local** — Codex can run on a local model; with that, the whole loop runs without outbound network.

## 13. Takeaways (0:45)

1. Coding agents already emit the signal. Give them a way to hear it.
2. You can build the loop entirely from open source: OpenTelemetry, Kafka, streaming SQL, and the agent's own hooks.
3. Keep detectors per-session, fire-once, and outside the agent.

**On screen:** `github.com/timeplus-io/osacon-2026`, `github.com/timeplus-io/proton` (QR codes).

---

## Likely questions

- **Why not put the checks in the agent's hook directly?** The hook only sees one call; the stream sees the whole session, every session, every agent, plus cost — and the logic is SQL you can test and review in one place. The hook stays a 2 ms lookup.
- **Latency?** ~100 ms inside Proton from event to decision; under a second from the agent's event to the decision being readable. It's applied at the next tool call, which comes seconds later anyway.
- **What if Proton is down?** The hook fails open; the agent runs normally.
- **Scale?** State is per session; partition the Kafka topic by session id.
- **Why Kafka and not OTLP straight into Proton?** Proton OSS doesn't have an OTLP receiver; Kafka is the standard bridge and the fan-out point for decisions.
- **Does it need ClickHouse?** No. Proton is standalone; it shares ClickHouse's columnar core and much of its SQL.
- **Claude Code isn't open source.** Right — it's the client being observed; Codex (Apache-2.0) works identically, and so would any agent with OTel export and pre-tool hooks.
