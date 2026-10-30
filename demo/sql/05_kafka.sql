-- ============================================================================
-- 05_kafka.sql — Kafka is the bridge between OpenTelemetry and Proton
--
-- In:  the OpenTelemetry Collector's kafka exporter writes each batch of log
--      events as OTLP/JSON to the `otlp_logs` topic; this external stream
--      reads it and a materialized view copies each message into otlp_logs_raw.
-- Out: every action is also published to the `agent_actions` topic for
--      anyone else (paging, audit, another controller).
--
-- Topics must exist before this runs (docker compose creates them).
-- ============================================================================

CREATE EXTERNAL STREAM IF NOT EXISTS otlp_logs_kafka
(
  raw string
)
SETTINGS type = 'kafka',
         brokers = 'kafka:9092',
         topic = 'otlp_logs',
         data_format = 'RawBLOB',
         one_message_per_row = true;

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_kafka_to_otlp_logs_raw INTO otlp_logs_raw AS
SELECT raw FROM otlp_logs_kafka;

CREATE EXTERNAL STREAM IF NOT EXISTS agent_actions_kafka
(
  session_id string,
  action     string,
  reason     string,
  hint       string,
  detector   string,
  target     string
)
SETTINGS type = 'kafka',
         brokers = 'kafka:9092',
         topic = 'agent_actions',
         data_format = 'JSONEachRow',
         one_message_per_row = true;

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_actions_to_kafka INTO agent_actions_kafka AS
SELECT session_id, action, reason, hint, detector, target FROM agent_actions;
