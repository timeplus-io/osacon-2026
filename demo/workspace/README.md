# checkout-api ops workspace

Runbooks and helper scripts for the `checkout-api` service (a fictional service
used for the OSA Con 2026 demo).

| Script | What it does |
|---|---|
| `./check_deploy.sh` | Shows the status of the current deploy |
| `./fetch_metrics.sh` | Pulls the last hour of error-rate metrics from the metrics API |

Other material:
- `metrics-cache/` — hourly snapshots of the metrics API, written by a cron job
- `postmortems/` — incident write-ups
