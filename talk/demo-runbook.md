# Demo runbook (on stage)

Target: 5 minutes. Everything runs from `demo/`.

## The night before

```bash
cd demo
cp .env.example .env        # ANTHROPIC_API_KEY, OPENAI_API_KEY; BUDGET_USD=0.15 if you'll show the halt
docker compose pull
docker compose build
docker compose up -d
docker compose run --rm simulator --scenario loop     # smoke test, no API key needed
```

Then run each live scenario once with each agent (prompts below) and confirm Grafana shows tool calls, alerts, and decisions.

- [ ] Record a backup video of the whole demo (laptop **and** USB stick).
- [ ] Note which model behaves best; pin it with `ANTHROPIC_MODEL` in `.env` if needed.
- [ ] Check the screen-share shows nothing from `.env`; close Slack/email.
- [ ] Terminal font ≥ 20pt. Grafana in a browser at 125% zoom, kiosk mode (`?kiosk`).
- [ ] Live agents need internet for the model API. If the venue Wi-Fi is bad, use a phone hotspot — or go straight to the simulator.

## At the venue (30 min before)

```bash
docker compose up -d
scripts/reset.sh          # empty streams, fresh schema, budgets from .env
```

Open http://localhost:3000/d/closing-the-loop?kiosk&refresh=5s

## Screen layout

| Left half | Right half |
|---|---|
| terminal: the agent | Grafana: *Decisions* (top), *Tool calls* (middle) |

A second terminal with `docker compose exec proton proton client` is handy for Q6 at the end.

## Beat 1 — polling loop, Claude Code: open the loop, then close it (~2.5 min)

Before the agent starts, open the loop (the policy view is gone; detectors still run):
```bash
scripts/policy.sh off
docker compose run --rm claude
```
Prompt:
```
Deploy #4182 is rolling out. Keep checking it with ./check_deploy.sh every ~10 seconds until it finishes, then tell me the result. Run each check as its own command, not a loop or a background job, so I can watch them.
```

Say, as it happens:
- While it polls: *"It's doing what I asked. The deploy will never finish. Watch the right side: tool calls streaming in, `tool_loop` alerts counting up — and nothing in Decisions. Right now this is observability. Everyone has this."*
- Let it run 20–40 s (8–16 checks). Then, in the SQL terminal: *"One materialized view closes the loop. This is slide 9."*
```bash
scripts/policy.sh on          # or paste the CREATE MATERIALIZED VIEW from sql/04_policy.sql
```
- Within four more checks a row lands in *Decisions*: *"Proton decided, ~100 ms after the event arrived."*
- When Claude Code shows the blocked call: *"Its own PreToolUse hook asked Proton, got 'interrupt', and denied the call. That sentence is now in front of the model."*
- When it answers: *"And it stops polling and tells me the deploy is stuck."*

Exit with `/exit` (or Ctrl-D twice). Leave the loop closed for Beat 2.

If the prompt that shows the blocked call doesn't come (the model stopped on its own before the next alert), ask it to *"keep checking"* — the decision is aimed at that one call, so the next identical call is the one that gets blocked.

## Beat 2 — retry storm, Codex (~1.5 min)

```bash
docker compose run --rm codex
```
Prompt:
```
Pull the last hour of error-rate metrics with ./fetch_metrics.sh and summarize them.
```

Say: *"Different agent, different telemetry vocabulary — same SQL, same hook protocol."* When it falls back to `metrics-cache/`: *"Three failures, then it was told to stop retrying and look for another source."*

If Codex gives up on its own after the third failure and goes straight to the cache, nothing is blocked — the interrupt is aimed at `./fetch_metrics.sh`, and Codex didn't call it again. Point at *Decisions* in Grafana: *"The stream decided; the agent had already moved on, so the hook let it through. It only blocks the call it's about."*

## Beat 3 — post-mortem (~30s)

Grafana *Alerts by detector*, or in the SQL terminal paste **Q6** from `sql/queries.sql`: *"Same engine, now answering a historical question — across both agents."*

## Optional — budget halt (if time; needs `BUDGET_USD=0.15`)

In Claude Code:
```
Read every postmortem in postmortems/ and write a summary of recurring root causes to SUMMARY.md.
```
When spend crosses the budget, the hook returns `continue: false` and Claude Code stops with the policy's reason. To show recovery, type:
```
[resume] the extra spend is approved, carry on
```
The halt lifts (and a `resume` row lands in *Decisions*); the budget re-arms at 2×. Operator alternative: `scripts/resume.sh <session_id>`.

## If a live agent doesn't cooperate

Real models vary: one might stop polling on its own after two checks, or vary the command. (The scripts are thin clients of the `ops-api` container, so the agent can't read the script and see that the deploy is synthetic; it still may decide to stop.) A separate `sleep 10` call between checks breaks the streak; `sleep 10 && ./check_deploy.sh` does not. Don't fight it on stage. Say *"the model got smart on its own — here's the same agent behavior, scripted"* and run:

```bash
docker compose run --rm simulator --scenario loop
docker compose run --rm simulator --scenario flaky
```

Same OpenTelemetry events, same Kafka, same SQL, same hook — Grafana lights up the same way.

## If something else breaks

- **No events in Grafana:** check the Collector — `docker compose logs otel-collector | tail` — then terminal **Q7** (raw payloads off Kafka).
- **Grafana panels empty but SQL works:** present from the terminal (Q1, Q3).
- **Anything worse:** play the backup video.
- **Schema errors after re-runs:** `scripts/reset.sh`.
