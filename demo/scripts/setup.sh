#!/usr/bin/env bash
# Apply the demo schema to a Proton server.
#
#   scripts/setup.sh              # direct mode: streams, parser, detectors, policy (no Kafka)
#   scripts/setup.sh --kafka      # also create the Kafka external streams (needs a broker + topics)
#
# Uses the `proton` binary on PATH (or $PROTON_BIN). With docker compose you
# don't need this — the proton-init service applies the same files.
set -euo pipefail
cd "$(dirname "$0")/../sql"

PROTON_BIN="${PROTON_BIN:-proton}"
PROTON_HOST="${PROTON_HOST:-localhost}"
KAFKA_BROKERS="${KAFKA_BROKERS:-}"

files=(01_streams.sql 02_parse_otlp.sql 03_detectors.sql 04_policy.sql)
for f in "${files[@]}"; do
  echo "applying $f"
  "$PROTON_BIN" client --host "$PROTON_HOST" --multiquery < "$f"
done

if [[ "${1:-}" == "--kafka" ]]; then
  echo "applying 05_kafka.sql${KAFKA_BROKERS:+ (brokers=$KAFKA_BROKERS)}"
  if [[ -n "$KAFKA_BROKERS" ]]; then
    sed "s/kafka:9092/$KAFKA_BROKERS/" 05_kafka.sql | "$PROTON_BIN" client --host "$PROTON_HOST" --multiquery
  else
    "$PROTON_BIN" client --host "$PROTON_HOST" --multiquery < 05_kafka.sql
  fi
fi
echo "schema ready"
