-- Drops everything the demo created (views first, then streams, then functions).
-- Not applied automatically; run by scripts/reset.sh for a clean slate.
DROP VIEW IF EXISTS mv_actions_to_kafka;
DROP VIEW IF EXISTS mv_kafka_to_otlp_logs_raw;
DROP VIEW IF EXISTS mv_policy;
DROP VIEW IF EXISTS mv_detect_budget;
DROP VIEW IF EXISTS mv_detect_tool_errors;
DROP VIEW IF EXISTS mv_detect_tool_loop;
DROP VIEW IF EXISTS mv_otlp_logs_to_events;
DROP STREAM IF EXISTS agent_actions_kafka;
DROP STREAM IF EXISTS otlp_logs_kafka;
DROP STREAM IF EXISTS agent_actions;
DROP STREAM IF EXISTS agent_alerts;
DROP STREAM IF EXISTS agent_session_log;
DROP STREAM IF EXISTS agent_events;
DROP STREAM IF EXISTS otlp_logs_raw;
DROP FUNCTION IF EXISTS agent_call_target;
DROP FUNCTION IF EXISTS otel_attrs;
