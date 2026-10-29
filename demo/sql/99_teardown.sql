-- Drops everything the demo created (views first, then streams).
-- Not applied by docker compose; run by scripts/reset.sh for a clean slate.
DROP VIEW IF EXISTS mv_actions_to_kafka;
DROP VIEW IF EXISTS mv_kafka_to_otlp_raw;
DROP VIEW IF EXISTS mv_policy;
DROP VIEW IF EXISTS mv_detect_token_burn;
DROP VIEW IF EXISTS mv_detect_tool_errors;
DROP VIEW IF EXISTS mv_detect_tool_loop;
DROP VIEW IF EXISTS mv_otlp_to_spans;
DROP STREAM IF EXISTS agent_actions_kafka;
DROP STREAM IF EXISTS otlp_kafka;
DROP STREAM IF EXISTS agent_actions;
DROP STREAM IF EXISTS agent_alerts;
DROP STREAM IF EXISTS agent_session_log;
DROP STREAM IF EXISTS agent_spans;
DROP STREAM IF EXISTS otlp_raw;
DROP FUNCTION IF EXISTS otel_attrs;
