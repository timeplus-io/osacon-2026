-- ============================================================================
-- 05_kafka.sql — Kafka edges (used by the docker-compose stack)
--
-- In:  the OpenTelemetry Collector's kafka exporter writes OTLP/JSON to the
--      `otlp_spans` topic; this external stream reads it and a materialized
--      view copies each message into otlp_raw.
-- Out: every action is also published to the `agent_actions` topic so other
--      systems (paging, dashboards, a second controller) can consume it.
--
-- Skip this file when running in direct mode (agent posts OTLP/JSON straight
-- to Proton's HTTP ingest endpoint).
-- ============================================================================

CREATE EXTERNAL STREAM IF NOT EXISTS otlp_kafka
(
  raw string
)
SETTINGS type = 'kafka',
         brokers = 'kafka:9092',
         topic = 'otlp_spans',
         data_format = 'RawBLOB',
         one_message_per_row = true;

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_kafka_to_otlp_raw INTO otlp_raw AS
SELECT raw FROM otlp_kafka;

CREATE EXTERNAL STREAM IF NOT EXISTS agent_actions_kafka
(
  session_id string,
  action     string,
  reason     string,
  hint       string
)
SETTINGS type = 'kafka',
         brokers = 'kafka:9092',
         topic = 'agent_actions',
         data_format = 'JSONEachRow',
         one_message_per_row = true;

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_actions_to_kafka INTO agent_actions_kafka AS
SELECT session_id, action, reason, hint FROM agent_actions;
