# Demo runbook, extras (not in the 20-minute slot)

These scenarios work and are rehearsed, but the talk shows only the Claude Code polling loop ([`demo-runbook.md`](demo-runbook.md)). Use these for Q&A, a hallway demo, or the recording. All commands run from `demo/`, with the loop **closed** (`scripts/policy.sh status` → `loop CLOSED`).

## Retry storm, Codex (~1.5 min)

```bash
docker compose run --rm codex
```
Prompt:
```
Pull the last hour of error-rate metrics with ./fetch_metrics.sh and summarize them.
```
The metrics API (the `ops-api` container, alias `metrics.internal`) always answers 503 "proxy restarting; retry". After three failures in a row `tool_errors` fires and the policy aims an interrupt at `./fetch_metrics.sh`.

Say: *"Different agent, different telemetry vocabulary, same SQL, same hook protocol."* When it falls back to `metrics-cache/`: *"Three failures, then it was told to stop retrying and look for another source."*

If Codex gives up on its own after the third failure and goes straight to the cache, nothing is blocked: the interrupt is aimed at `./fetch_metrics.sh`, and Codex didn't call it again. Point at *Decisions*: *"The stream decided; the agent had already moved on, so the hook let it through. It only blocks the call it's about."*

Simulator stand-in: `docker compose run --rm simulator --scenario flaky`.

## Post-mortem query (~30 s)

Grafana *Alerts by detector*, or in `docker compose exec proton proton client` paste **Q6** from `sql/queries.sql`: *"Same engine, now answering a historical question, across both agents."* Q5 replays one session from its log.

## Budget halt and resume (~1.5 min, needs `BUDGET_USD=0.15` in `.env` and `scripts/reset.sh`)

In Claude Code:
```
Read every postmortem in postmortems/ and write a summary of recurring root causes to SUMMARY.md.
```
When session spend crosses the budget, `budget` fires, the policy writes a `halt`, every tool call is denied, and the PostToolUse hook ends the turn with the policy's reason. To show recovery, type:
```
[resume] the extra spend is approved, carry on
```
The halt lifts (a `resume` row lands in *Decisions*) and the budget re-arms at 2×. Operator alternative: `scripts/resume.sh <session_id>`. Simulator stand-in: `--scenario burn`.

## Escalation (if asked)

An agent that ignores two interrupts gets a halt on the third failing pattern in the same session: with the loop closed, interrupts at the 4th and 8th identical call, halt at the 12th. `[resume]` lifts it. The e2e test covers this (`tests/e2e_test.py`, "escalation").
