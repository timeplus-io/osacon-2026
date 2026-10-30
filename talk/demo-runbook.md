# Demo runbook (on stage): Claude Code polls, the stream closes the loop

One demo, target **4 minutes**. Everything runs from `demo/`. The other scenarios (Codex retry storm, post-mortem query, budget halt) are in [`demo-runbook-extras.md`](demo-runbook-extras.md) and are only for Q&A or a hallway demo.

## The idea in one line

With the policy view **dropped**, Proton only observes: tool calls stream in, `tool_loop` alerts count up, nothing reaches the agent. **Creating the view** turns the next alert into a decision, the agent's own hook denies the next identical call, and the model stops polling and reports. The whole switch is one `CREATE MATERIALIZED VIEW`.

## The night before

```bash
cd demo
cp .env.example .env        # ANTHROPIC_API_KEY (purchased credit, not promo); ANTHROPIC_MODEL=claude-opus-5-5
docker compose pull
docker compose build
docker compose up -d
docker compose run --rm simulator --scenario loop     # smoke test, no API key needed
```

Then run the live demo below once, end to end, against the clock.

- [ ] Record a backup video of the demo (laptop **and** USB stick).
- [ ] Note which model behaves; pin it with `ANTHROPIC_MODEL` in `.env`.
- [ ] Disable the laptop's own Claude Code telemetry (`~/.claude/settings.json`, `OTEL_EXPORTER_OTLP_ENDPOINT`), or your other sessions show up in Grafana.
- [ ] Check the screen-share shows nothing from `.env`; close Slack/email.
- [ ] Terminal font ≥ 20pt. Grafana in a browser at 125% zoom, kiosk mode (`?kiosk`).
- [ ] Live agents need internet for the model API. If the venue Wi-Fi is bad, use a phone hotspot, or go straight to the simulator.

## At the venue (30 min before)

```bash
docker compose up -d
scripts/reset.sh          # empty streams, fresh schema, budgets from .env
scripts/policy.sh off     # OPEN the loop: drops mv_policy; detectors keep running
scripts/policy.sh status  # must print: loop OPEN (no mv_policy)
```

Open http://localhost:3000/d/closing-the-loop?kiosk (no auto-refresh: every panel streams).

## Screen layout

| Left half | Right half |
|---|---|
| terminal A: the agent (`docker compose run --rm claude`) | Grafana: *Decisions* (top), *Tool calls* (middle), *Alerts by detector* (right) |
| terminal B: `cd demo`, for the switch | |

## The demo, step by step

**1. Confirm the loop is open** (terminal B, before anyone looks):
```bash
scripts/policy.sh status      # loop OPEN (no mv_policy)
```

**2. Start the agent** (terminal A):
```bash
docker compose run --rm claude
```
Prompt (copy exactly):
```
Deploy #4182 is rolling out. Keep checking it with ./check_deploy.sh every ~10 seconds until it finishes, then tell me the result. Run each check as its own command, not a loop or a background job, so I can watch them.
```

**3. Let it poll, 20–40 s (8–16 checks).** Say:
> *"It's doing what I asked. The deploy will never finish. Watch the right side: tool calls streaming in, `tool_loop` alerts counting up, and nothing in Decisions. Right now this is observability. Everyone has this."*

**4. Close the loop** (terminal B). Say *"One materialized view closes the loop. This is the SQL on the 'Decide and deliver' slide."* Then either:
```bash
scripts/policy.sh on          # = proton client --multiquery < sql/04_policy.sql
```
or, for the live-typing version, paste the `CREATE MATERIALIZED VIEW mv_policy ...` statement from `sql/04_policy.sql` into `docker compose exec proton proton client`.

**5. Watch it land.** The detector fires on every 4th identical check, so within at most four more checks:
- a row appears in *Decisions*: *"Proton decided, ~100 ms after the event arrived."*
- Claude Code shows the denied call with the policy's sentence: *"Its own PreToolUse hook asked Proton, got 'interrupt', and denied the call. That sentence is now in front of the model."*
- the model answers: *"And it stops polling and tells me the deploy is stuck."*

**6. Close.** Point at *Decisions* once more: *"Detection ran in the background; enforcement was one lookup in the agent's own hook. No scheduler, no sidecar, one SQL view."* Exit with `/exit`.

## What the switch actually does

| | command | effect |
|---|---|---|
| open | `scripts/policy.sh off` → `DROP VIEW IF EXISTS mv_policy` | alerts still written to `agent_alerts`; `agent_actions` gets nothing; hooks allow everything |
| close | `scripts/policy.sh on` → applies `sql/04_policy.sql` | from the next alert on, `agent_actions` gets a decision; the hook denies the next matching call |

The view starts from "now": alerts that fired while the loop was open are not replayed. That is why the detector fires on every 4th identical call rather than only at 4/8/12.

## If the agent doesn't cooperate

- **It stops polling on its own before the decision lands.** Type `keep checking` in Claude Code. The decision is aimed at that one call, so the next identical check is the one that gets denied.
- **It writes a loop or a background job.** Claude Code will ask for permission (the command isn't on the allowlist). Decline, and it falls back to single calls.
- **It reads the script.** Fine: `check_deploy.sh` is a thin client of the `ops-api` container and shows nothing synthetic.
- **It varies the command** (`sleep 10 && ./check_deploy.sh` still counts; a separate `sleep` call breaks the streak). Don't fight it. Say *"the model got smart on its own. Here's the same agent behaviour, scripted"* and run:
  ```bash
  docker compose run --rm simulator --scenario loop
  ```
  Same OpenTelemetry events, same Kafka, same SQL, same hook; Grafana lights up the same way. Do steps 1 and 4 around it exactly as above.

## If something else breaks

- **No events in Grafana:** `docker compose logs otel-collector | tail`, then terminal **Q7** from `sql/queries.sql` (raw payloads off Kafka).
- **Grafana panels empty but SQL works:** present from the terminal (**Q1** live tail, **Q3** decisions).
- **`policy.sh on` fails:** `scripts/reset.sh`, then `scripts/policy.sh off` again, restart the agent.
- **Anything worse:** play the backup video.
