# Talk outline and speaker notes

**Closing the Loop with Open Source: Streaming SQL from Agent Telemetry to Agent Action**
20 minutes + 5 minutes Q&A · 11 main slides + 9 backup · one 4-minute live demo (Claude Code polling loop; the simulator is the fallback)

Ground rules for this venue (from the organizers): open source only, no commercial content, the room is livestreamed and recorded. The infrastructure on screen is all OSS (OpenTelemetry, Kafka, Proton, Grafana). The agents are the *clients* being observed: Codex is open source (Apache-2.0); Claude Code is not, so say once that the loop works the same for any agent that exports OTel and has hooks. No customer names; nothing confidential on slides, terminals, or in `.env`.

The speaker notes in the deck are the source of truth for what to say; this file mirrors them in short form.

---

## Timing at a glance

| # | Slide | Time | Cumulative |
|---|---|---|---|
| 1 | Title | 0:30 | 0:30 |
| 2 | Agents can act on their own telemetry | 1:00 | 1:30 |
| 3 | Agents already speak OpenTelemetry | 1:00 | 2:30 |
| 4 | Three agent failures burn money within seconds | 1:30 | 4:00 |
| 5 | The loop: signal out, decision back in | 1:30 | 5:30 |
| 6 | Timeplus Proton: SQL that never stops running | 1:00 | 6:30 |
| 7 | Inside Proton | 0:45 | 7:15 |
| 8 | The pipeline: streams hold data, views do the work | 2:30 | 9:45 |
| 9 | **Live demo**: observe first, then one SQL view closes the loop | 4:00 | 13:45 |
| 10 | Summary: why Proton | 1:00 | 14:45 |
| 11 | Try it yourself (links, QR to timeplus.com) | 0:30 | 15:15 |
| — | *Backup: divider, agent events, detect, decide and deliver, the hook, configuration, parse view, timing, open problems* | Q&A only | |

About 4:45 of slack. Spend it on the demo if the agent is slow; otherwise take questions early. If a live agent doesn't cooperate, switch to the simulator (same pipeline), see `demo-runbook.md`. Don't debug on stage.

---

## 1. Title (0:30)

> I work on Proton, an open-source streaming SQL engine. Today is about a loop every team running coding agents will need, built from open parts. Everything I show is in the repo at the end, and it runs with one `docker compose up`.

## 2. Agents can act on their own telemetry (1:00)

**On screen:** illustration (dashboard-only vs. closed loop) and *"The same data pipeline can feed two readers: a dashboard for humans, and a hook that hands decisions back to the agent."*

> For twenty years telemetry has had one reader: a human, through a dashboard or an alert. Agents produce far more of it, because every step is a model call or a tool call, and they are the first systems that can read a signal about themselves and change course. So the same stream gets a second reader: the agent itself. The dashboard stays, for us; the loop doesn't need it.

## 3. Agents already speak OpenTelemetry (1:00)

**On screen:** coding agent → *built in* → OpenTelemetry → logs/events (pink), metrics, traces. Bar: *"Nobody has to instrument anything. The signal is already there."*

> OpenTelemetry is the open standard for telemetry: one protocol, OTLP, for logs, metrics and traces. Claude Code and Codex have it built in; a few environment variables or one config block turn it on. The part we use is the log events: one for every tool call and model call, with the tool, its arguments, success, tokens and cost. (Example events side by side: backup.)

## 4. Three agent failures burn money within seconds (1:30)

**On screen:** three illustrated cards: polling loop, retry storm, runaway spend, each with its signature in the telemetry.

> If you have run coding agents you have seen all three. By the time a human looks at a dashboard, the agent has made dozens of calls and spent real money. Each failure has a clear signature in the telemetry, which is what makes it detectable in SQL. Today's demo is the first one; the other two are in the repo.

## 5. The loop: signal out, decision back in (1:30)

**On screen:** coding agent → OTel Collector → Apache Kafka → Proton → Grafana, and the pink loop underneath: Proton → `agent_actions` → PreToolUse hook → agent.

> Signal goes out over standard OpenTelemetry. Proton doesn't speak OTLP and doesn't need to: the Collector writes OTLP/JSON to Kafka. Proton turns it into decisions with streaming SQL, and the agent's own PreToolUse hook reads them before its next tool call. Two readers of one stream: the pink loop runs with nobody watching; Grafana is for us, and optional.

## 6. Timeplus Proton: SQL that never stops running (1:00)

**On screen:** four facts (Apache-2.0, one C++ binary, ClickHouse-derived, live + history) and the same query streaming (`FROM agent_events`) and historical (`FROM table(agent_events)`).

> A streaming query never finishes: point a SELECT at a stream and it pushes each new matching row as it arrives. Wrap it in `table()` and it scans what's stored and returns. A materialized view is a streaming query that runs forever and writes into another stream. Every detector and policy here is one. No scheduler, no cron.

## 7. Inside Proton (0:45)

> One binary. Writes land in NativeLog, an append-only streaming log, and in a columnar historical store. Streaming queries read the log; batch queries read the store. External streams read Kafka, Redpanda or Pulsar directly; the OTel topic in this demo is one.

## 8. The pipeline: streams hold data, views do the work (2:30)

**On screen:** data lineage: `otlp_logs` → `mv_otlp_logs_to_events` → `agent_events` → `mv_detect_*` → `agent_alerts` → `mv_policy` → `agent_actions` → PreToolUse hook.

> The streams are thin; the pink cards are materialized views and they do all the work. One parses OTLP into one schema for both agents. Three detectors keep per-session state: four identical calls in a row, three failures in a row, spend over budget. The policy turns alerts into decisions aimed at one specific tool call.
>
> The key design choice: detection is asynchronous, enforcement is synchronous. The agent never waits for the views. Before every tool call its hook does one lookup: is there a decision aimed at this call? A match is blocked once, with the policy's hint as the reason the model reads. Ignore the hint twice and it's a halt, which a person lifts with `[resume]`.

## 9. Live demo (4:00)

Follow `demo-runbook.md`. Before going on stage the policy view is paused (`scripts/policy.sh off`), so the loop is open.

1. **Observe** (30–60 s). Claude Code is told to wait for deploy #4182 with `./check_deploy.sh`. It polls. *"Tool calls stream in, `tool_loop` alerts count up, and nothing in Decisions. Right now this is observability. Everyone has this."*
2. **Close the loop.** *"One materialized view closes the loop, and it has been paused. Resume it."* `scripts/policy.sh on` (`SYSTEM RESUME MATERIALIZED VIEW mv_policy`).
3. **Watch it land.** Proton replays what it observed: the alerts become decisions at once, the hook denies the next check with the policy's sentence, and the model stops polling and reports the deploy is stuck. *"Detection ran in the background; enforcement was one lookup in the agent's own hook. No scheduler, no sidecar, one SQL view."*

Fallback: `docker compose run --rm simulator --scenario loop`. Retry storm, post-mortem and budget halt are in `demo-runbook-extras.md`, for Q&A only.

## 10. Summary: why Proton (1:00)

**On screen:** 1 Reacts in milliseconds · 2 Every rule is just SQL · 3 Open, runs anywhere. Bar: *"Agents emit the signal. Proton turns it into a decision before the next tool call."*

> Agents act every few seconds, so the decision has to come from the event itself, per session, before the next tool call. Every rule is a materialized view you can read, review and change as you learn. And it's one small Apache-2.0 binary on the OpenTelemetry and Kafka you already run, even with no outbound network.

## 11. Try it yourself (0:30)

**On screen:** demo repo (`github.com/timeplus-io/osacon-2026`, `cd demo && docker compose up`), Proton repo, timeplus.com, Slack, LinkedIn and email; QR code to timeplus.com.

> The repo has the full stack, Claude Code and Codex preconfigured, plus an offline simulator. The retry storm and runaway spend scenarios are in there too. Thanks.

---

## Backup (Q&A only)

| Slide | Use it when someone asks |
|---|---|
| Agent events | "What does the telemetry actually look like?" |
| Detect | "Show me a detector." (`sql/03_detectors.sql`) |
| Decide and deliver | "How does the decision reach the agent? What about a halt?" (`sql/04_policy.sql`) |
| The hook | "What does your hook actually do?" (`hooks/proton_gate.py`: PreToolUse lookup, deny once, halt, `[resume]`, fail open) |
| Configuration | "How do I turn the signal on?" |
| Parse view | "How do both agents map to one schema?" |
| Timing | "Why not block the call that triggered it?" or "What about rm -rf?" |
| Open problems | "Semantic loops? Fully local?" |

Lessons from building it, if asked: time windows for per-session detection failed (the watermark is shared across sessions, so one session's alert waited for another's events, then fired nine times); exact-match on tool arguments missed the loop (the Bash description changes every call), so compare the normalized target; detecting inside the agent doesn't work, because the agent is the thing that's broken.

## Likely questions

- **Why not block the call that triggered the alert?** Detection is asynchronous by design — the agent never waits for the stream. The pattern takes four calls to form; the next matching call is blocked. Single-call rules (`rm -rf`, secrets) belong in the hook or the agent's permissions, checked synchronously.
- **Won't it block legitimate work?** An interrupt is aimed at the call it's about. If the agent has moved on, its next call runs. It blocks once, and expires after a minute.
- **How do you recover from a halt?** A person types `[resume]` in the session (the hook sees it before the model), or an operator runs `scripts/resume.sh`. It's recorded in `agent_actions`. The budget re-arms at 2×.
- **What if the stream is down?** No new decisions; the agent runs normally. The hook times out after 1.5 s and allows the call.

- **Why not put the checks in the agent's hook directly?** The hook only sees one call; the stream sees the whole session, every session, every agent, plus cost — and the logic is SQL you can test and review in one place. The hook stays one lookup (~15 ms query).
- **Latency?** ~100 ms inside Proton from event to decision; under a second from the agent's event to the decision being readable. It's applied at the next tool call, which comes seconds later anyway.
- **What if Proton is down?** The hook fails open; the agent runs normally.
- **Scale?** State is per session; partition the Kafka topic by session id.
- **Why Kafka and not OTLP straight into Proton?** Proton OSS doesn't have an OTLP receiver; Kafka is the standard bridge and the fan-out point for decisions.
- **Does it need ClickHouse?** No. Proton is standalone; it shares ClickHouse's columnar core and much of its SQL.
- **Claude Code isn't open source.** Right — it's the client being observed; Codex (Apache-2.0) works identically, and so would any agent with OTel export and pre-tool hooks.
