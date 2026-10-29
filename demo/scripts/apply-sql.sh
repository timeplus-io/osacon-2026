#!/usr/bin/env bash
# Apply the demo schema (sql/0*.sql) to Proton. Idempotent: everything is
# CREATE ... IF NOT EXISTS. Used by the proton-init container; also runnable
# by hand against any Proton.
#
#   PROTON_HOST     proton host               (default: proton)
#   PROTON_BIN      proton binary             (default: proton)
#   KAFKA_BROKERS   broker list for 05_kafka   (default: kafka:9092)
#   BUDGET_USD      session budget in USD      (default: 0.50)
#   BUDGET_TOKENS   session budget in tokens   (default: 200000)
set -euo pipefail
SQL_DIR="${SQL_DIR:-$(cd "$(dirname "$0")/../sql" && pwd)}"
PROTON_BIN="${PROTON_BIN:-proton}"
PROTON_HOST="${PROTON_HOST:-proton}"
KAFKA_BROKERS="${KAFKA_BROKERS:-kafka:9092}"
BUDGET_USD="${BUDGET_USD:-0.50}"
BUDGET_TOKENS="${BUDGET_TOKENS:-200000}"

for f in "$SQL_DIR"/0*.sql; do
  echo "applying $(basename "$f")"
  sed -e "s/__BUDGET_USD__/${BUDGET_USD}/g" \
      -e "s/__BUDGET_TOKENS__/${BUDGET_TOKENS}/g" \
      -e "s/kafka:9092/${KAFKA_BROKERS}/g" "$f" \
    | "$PROTON_BIN" client --host "$PROTON_HOST" --multiquery
done
echo "schema ready (budget: \$${BUDGET_USD} / ${BUDGET_TOKENS} tokens)"
