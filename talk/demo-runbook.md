# Demo runbook (on stage)

Target: 5 minutes, three beats. Everything below runs from `demo/`.

## Before the talk (at the hotel / the night before)

```bash
cd demo
docker compose pull                       # pull images while you have good network
docker compose build agent
docker compose up -d                      # proton, kafka, otel-collector, schema
docker compose run --rm agent --scenario loop   # smoke test
```

- [ ] Record a backup video of the full demo (all three beats) and keep it on the laptop **and** the USB stick.
- [ ] Turn off notifications; close Slack, email, and anything with customer names.
- [ ] Terminal font ≥ 20pt, dark background, window cleared.
- [ ] Confirm it runs with Wi-Fi **off** (images cached, nothing needs the network).

## At the venue (30 min before)

```bash
docker compose up -d
scripts/reset.sh                          # empty streams, fresh schema
```

## Terminal layout

| Pane | Command | Purpose |
|---|---|---|
| A (large, left) | `docker compose run --rm agent ...` | the agent |
| B (top right) | `docker compose exec proton proton client` → paste **Q3** from `sql/queries.sql` | decisions as they happen |
| C (bottom right) | `docker compose exec proton proton client` → paste **Q1** | live span tail (optional; drop if the screen is crowded) |

Start Q3 (and Q1) *before* beat 1 — streaming queries only show what arrives after they start.

## Beat 1 — the loop, nobody listening (~45s)

```bash
docker compose run --rm agent --scenario loop --no-control --max-steps 10
```

Say: *"Same search, again and again. Look at the right pane: Proton caught it on the fourth call. But this agent isn't subscribed — the signal exists and nobody hears it. That's most stacks today."*

## Beat 2 — close the loop (~90s)

```bash
docker compose run --rm agent --scenario loop
```

Say, as it happens:
- On `◀ proton interrupt`: *"Fourth identical call, and the decision is back in the agent — read the latency on screen."*
- On `hint →`: *"The policy injects a hint, like a system message."*
- On `✔ answer`: *"It changes strategy and finishes."*

Optional (if time): in pane B, Ctrl-C and paste **Q4** — alerts joined with the user's goal from the session log.

## Beat 3 — runaway cost (~60s)

```bash
docker compose run --rm agent --scenario burn
```

Say: *"Every step re-reads everything, so tokens grow each call. When the last five calls cross 20k tokens, the policy halts it — no human in the loop."*

## Close (~15s)

Pane B: Ctrl-C, paste **Q6**. *"Same engine, now answering a historical question: what fired, across every session."*

## If something breaks

- **Agent hangs at start / no `◀ proton` line:** don't debug. Say *"live demos — here's the recording"* and play the backup video.
- **Compose stack won't start:** fall back to the local binary path (no Docker): `proton server` in one pane, then `scripts/setup.sh` and `python agent/agent.py --scenario loop` (direct mode). See `demo/README.md`.
- **Schema errors after a re-run:** `scripts/reset.sh`.
