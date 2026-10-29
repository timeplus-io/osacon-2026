-- ============================================================================
-- 01_streams.sql — the streams that make up the loop
--
--   otlp_raw           OTLP/JSON trace payloads, one ExportTraceServiceRequest per row
--   agent_spans        flattened spans (one row per span, GenAI semantic conventions)
--   agent_session_log  the agent's own append-only session log
--   agent_alerts       what the detectors found
--   agent_actions      what the policy decided — the agent subscribes to this
-- ============================================================================

CREATE STREAM IF NOT EXISTS otlp_raw
(
  raw string
)
COMMENT 'Raw OTLP/JSON trace payloads (from Kafka via the OTel Collector, or posted directly)';

CREATE STREAM IF NOT EXISTS agent_spans
(
  start_time      datetime64(3),
  duration_ms     float64,
  service         string,
  trace_id        string,
  span_id         string,
  parent_span_id  string,
  span_name       string,
  status_code     int8,          -- OTLP status: 0 unset, 1 ok, 2 error
  session_id      string,        -- gen_ai.conversation.id
  agent_name      string,        -- gen_ai.agent.name
  operation       string,        -- gen_ai.operation.name: invoke_agent | chat | execute_tool
  model           string,        -- gen_ai.request.model
  tool_name       string,        -- gen_ai.tool.name
  tool_args       string,        -- gen_ai.tool.call.arguments
  input_tokens    uint32,        -- gen_ai.usage.input_tokens
  output_tokens   uint32,        -- gen_ai.usage.output_tokens
  attributes      map(string, string)
)
COMMENT 'One row per OTel span emitted by the agent';

CREATE STREAM IF NOT EXISTS agent_session_log
(
  session_id  string,
  seq         uint32,
  event_type  string,   -- user_goal | llm_decision | tool_call | tool_result | control | final_answer | halted
  content     string
)
COMMENT 'Append-only session log written by the agent runtime itself';

CREATE STREAM IF NOT EXISTS agent_alerts
(
  session_id  string,
  detector    string,
  severity    string,
  detail      string,
  evidence    string
)
COMMENT 'Detector output';

CREATE STREAM IF NOT EXISTS agent_actions
(
  session_id  string,
  action      string,   -- interrupt | halt
  reason      string,
  hint        string    -- injected back into the agent''s context on interrupt
)
COMMENT 'Decisions fed back to the running agent';
