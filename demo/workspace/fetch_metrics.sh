#!/usr/bin/env bash
# Demo: an upstream that is down. Looks transient, so agents retry it.
echo "fetching error_rate{service=\"checkout-api\"}[1h] from https://metrics.internal ..." >&2
sleep 1
echo "curl: (7) Failed to connect to metrics.internal port 443 after 1002 ms: Connection refused" >&2
echo "hint: the metrics proxy restarts occasionally; retrying usually works" >&2
exit 7
