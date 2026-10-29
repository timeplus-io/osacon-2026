# Talk outline and speaker notes

**Closing the Loop with Open Source: Streaming SQL from Agent Telemetry to Agent Action**
20 minutes + 5 minutes Q&A · 13 slides · ~5 minutes of live demo

Ground rules for this venue (from the organizers): open source only, no commercial content, the room is livestreamed and recorded. Every product on screen is OSS; no customer names; nothing confidential on slides or in terminals.

---

## Timing at a glance

| # | Slide | Time | Cumulative |
|---|---|---|---|
| 1 | Title | 0:30 | 0:30 |
| 2 | Agents can act on their own telemetry | 1:00 | 1:30 |
| 3 | What agent telemetry looks like | 1:30 | 3:00 |
| 4 | Failures that happen in seconds | 1:15 | 4:15 |
| 5 | The loop | 0:45 | 5:00 |
| 6 | Signal: OTel + the session log | 1:30 | 6:30 |
| 7 | Engine: Proton, and parsing OTLP in SQL | 1:30 | 8:00 |
| 8 | A detector is a materialized view | 1:30 | 9:30 |
| 9 | The policy is SQL; the agent subscribes | 1:00 | 10:30 |
| 10 | **Live demo** | 5:00 | 15:30 |
| 11 | What held up, what didn't | 2:30 | 18:00 |
| 12 | Open problems | 1:15 | 19:15 |
| 13 | Takeaways + repo | 0:45 | 20:00 |

If the demo runs long, cut slide 12 to one sentence. If the demo fails, switch to the recording (see `demo-runbook.md`) and don't debug on stage.

---

## 1. Title (0:30)

**On screen:** title, name, Timeplus, repo URL `github.com/timeplus-io/osacon-2026`.

> I work on Proton, an open-source streaming SQL engine. Today is not about Proton, though — it's about a loop that every team running agents will need, and how to build it from open parts. Everything I show is in that repo, including the demo.

## 2. Agents are the first systems that can act on their own telemetry (1:00)

**On screen:** one line — *"Observe later" is a postmortem. Agents need "observe now, act now."*

> For twenty years telemetry has been for humans: we collect it, we put it on a dashboard, someone looks at it during an incident. Agents change that in two ways. They produce far more of it — every step is a model call, a tool call, a retrieval. And they're the first systems that can read a signal about themselves and change course. If the only consumer of agent telemetry is a dashboard, we're leaving the most useful reader out.

## 3. What agent telemetry looks like (1:30)

**On screen:** a trace of one agent run: `invoke_agent` root → alternating `chat` and `execute_tool` spans. Callouts for the GenAI semantic convention attributes: `gen_ai.operation.name`, `gen_ai.conversation.id`, `gen_ai.tool.name`, `gen_ai.tool.call.arguments`, `gen_ai.usage.input_tokens / output_tokens`.

> This is an OpenTelemetry trace of one agent session, using the GenAI semantic conventions. Three differences from a web request. It's long — minutes, not milliseconds. It branches — the model decides the shape at runtime. And it carries cost on every span: tokens. The conventions matter because they give us a stable schema to write SQL against, regardless of which framework built the agent.

## 4. Failures that happen in seconds (1:15)

**On screen:** three cards — **Loop** (same tool, same args, again and again) · **Retry storm** (a dependency is down; the agent keeps hammering it) · **Context blowup** (each step re-reads everything; tokens grow quadratically).

> These aren't exotic. If you've run agents you've seen all three. What they have in common: by the time a human looks at a dashboard, the agent has made dozens of calls and spent real money. An agent loops three times a second. A five-minute alerting interval is a very long time.

## 5. The loop (0:45)

**On screen:** the architecture diagram from `docs/architecture.md`: agent → OTel Collector → Kafka → Proton (parse → detect → policy) → back to the agent.

> Here's the whole thing. Signal goes out over standard OpenTelemetry. Proton turns it into decisions with streaming SQL. Decisions come back to the agent over a live query. Four open-source pieces, no custom services in the middle.

## 6. Signal: OpenTelemetry + the session log (1:30)

**On screen:** left — Collector config snippet (`kafka` exporter, `encoding: otlp_json`). Right — the session log stream: `user_goal`, `llm_decision`, `tool_call`, `tool_result`, `control`, `final_answer`.

> Two signals. Traces tell you what the agent did, with timing and cost, in a standard format — the Collector writes them to Kafka as OTLP/JSON, no custom exporter. The second signal is the agent's own append-only session log: what it was asked, what it decided, what came back. Traces are what happened; the log is why. Keeping the log as a stream means you can join the two, and you can replay any session from it later.

## 7. Engine: Proton, and parsing OTLP in SQL (1:30)

**On screen:** one-line description — *Proton: Apache 2.0, single binary, ClickHouse-derived, streaming + historical SQL in one engine.* Then the core of `sql/02_parse_otlp.sql` — the `array_join` that flattens `resourceSpans → scopeSpans → spans` and the `otel_attrs` UDF.

> Proton is a streaming SQL engine built on ClickHouse's columnar core. Single binary, no JVM, runs on a laptop or a t2.nano. The same SQL works on live streams and on history. First job: OTLP/JSON is nested three levels deep with attributes as key-value arrays. That's one materialized view — every payload that lands in Kafka becomes flat, typed rows within milliseconds.

## 8. A detector is a materialized view (1:30)

**On screen:** `sql/03_detectors.sql`, D1 (tool loop). Highlight `PARTITION BY session_id` and `lags(call_key, 1, 4)`.

> This is the loop detector, the whole thing. `PARTITION BY session_id` gives every session its own state. `lags` looks at that session's last four tool calls. Same tool, same arguments, four times in a row — fire, once. It's a materialized view, so it runs forever and nobody has to schedule it. The other two detectors — three tool failures in a row, and token burn over the last five model calls — are the same shape.

## 9. The policy is SQL; the agent subscribes (1:00)

**On screen:** `sql/04_policy.sql` (`multi_if` mapping detector → `interrupt` / `halt` + hint text), and the one line in the agent: `SELECT action, reason, hint FROM agent_actions WHERE session_id = ...`.

> Alerts become actions with one more view. "Interrupt" means: inject a hint into the agent's context and let it keep going. "Halt" means stop. Because it's SQL, the policy is reviewable — it goes through code review like anything else. The agent holds a streaming query filtered to its own session. Proton pushes the row the moment it exists. No polling interval to tune.

## 10. Live demo (5:00)

Follow `demo-runbook.md` exactly. Three beats:

1. **Loop, control off** (~45s). `--scenario loop --no-control --max-steps 10`. The agent searches the same thing over and over; the actions pane shows Proton *did* catch it — but nobody's listening. *"This is what most stacks look like today: the signal exists, the agent never hears it."*
2. **Loop, control on** (~90s). Same agent. Fourth identical call → `◀ proton interrupt` → hint → agent switches to the docs and answers. Read out the latency printed on screen (typically 200–350 ms after the triggering call). Point at Q4: the alert joined with the user's original goal from the session log.
3. **Burn** (~60s). `--scenario burn`. Context grows every step; Proton halts it when the last five calls cross 20k tokens.

Close with Q6 (post-mortem across all sessions) — *"the same engine, now answering a historical question."*

## 11. What held up, what didn't (2:30)

**On screen:** two columns.

**Held up**
- Per-session state (`PARTITION BY`) instead of global windows.
- Fire once, on the crossing. Detectors that fire every second are noise; agents and humans both stop listening.
- Interrupt before halt. A hint usually fixes a loop; save "halt" for budgets.
- One wire format (OTLP/JSON) for every path: Collector → Kafka, or direct ingest when offline.
- Policy in SQL, versioned with the rest of the code.

**Didn't**
- Time windows for per-session detection. Our first token-burn detector used a sliding 10-second window. Windows close on the watermark, and the watermark is shared across sessions — so one session's alert waited for *another* session's events, then fired nine times. Row-based, per-session state fixed both.
- Detecting inside the agent process. The agent is the thing that's broken; the watcher has to be outside it.
- Polling a table for decisions. A push subscription is simpler and faster.

> The window story is a real one from building this demo last week, and it generalizes: think about whose events advance your clock.

## 12. Open problems (1:15)

- **Semantic loops** — same intent, different arguments. Needs embeddings in the pipeline, which costs latency and money.
- **Multi-agent causality** — when agent A's output loops agent B, the pattern spans traces.
- **Who watches the policy** — interrupts can oscillate; the loop needs its own telemetry.
- **Sensitive content in spans** — prompts and tool arguments in attributes are a data-governance problem, not just a storage one.
- **Fully local** — everything here runs with no outbound network; the open question is doing semantic checks with local models at stream speed.

## 13. Takeaways (0:45)

1. Agent telemetry is an input, not just an output. Give the agent a way to hear it.
2. You can build the loop entirely from open source: OpenTelemetry, Kafka, streaming SQL.
3. Keep detectors per-session, fire-once, and outside the agent.

**On screen:** `github.com/timeplus-io/osacon-2026` and `github.com/timeplus-io/proton` (QR codes).

> The repo has the full stack — `docker compose up` and you have the demo. Thanks.

---

## Likely questions

- **Why not just put the checks in the agent framework?** The agent is the thing failing, checks inside it share its blind spots, and you'd reimplement them per framework. A stream sees every agent through one schema.
- **Latency?** On a laptop, ~100 ms from span arrival to alert inside Proton; ~200–350 ms from the agent's call completing to the action arriving, most of it the OTel batch delay (200 ms, configurable).
- **Scale?** Detectors are per-session state; sessions are independent, so this partitions cleanly by `session_id` on the Kafka topic.
- **Why not a time-series DB / batch alerting?** You can, for dashboards. The loop needs push semantics and per-key state with sub-second reaction, which is what a streaming engine is for.
- **Is the LLM real?** In the demo, no — it's a deterministic stand-in so the demo is reproducible offline. The telemetry, transport, detection, and feedback path are all real; swapping in a real model only changes `MockLLM`.
- **Does it need ClickHouse?** No. Proton is standalone; it shares ClickHouse's columnar core and much of its SQL dialect.
