# checkout-api ops workspace

Helper scripts for day-to-day operation of the `checkout-api` service.

| Script | What it does |
|---|---|
| `./check_deploy.sh [id]` | Shows the status of a deploy via the deploy service (default: the one in progress) |
| `./fetch_metrics.sh` | Pulls the last hour of error-rate metrics from the metrics API |

Other material:
- `metrics-cache/` — hourly snapshots of the metrics API, written by a cron job
- `postmortems/` — incident write-ups
