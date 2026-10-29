-- ============================================================================
-- 01_streams.sql — the streams that make up the loop
--
--   otlp_logs_raw      OTLP/JSON log payloads from Kafka (one ExportLogsServiceRequest per row)
--   agent_events       one row per agent event: tool calls, model calls, prompts
--                      (Claude Code, Codex, or the offline simulator — one schema)
--   agent_session_log  the agent's own append-only log, written by its hooks
--   agent_alerts       what the detectors found
--   agent_actions      what the policy decided — the agent's hook reads this
-- ============================================================================

CREATE STREAM IF NOT EXISTS otlp_logs_raw
(
  raw string
)
COMMENT 'Raw OTLP/JSON log payloads, copied from the Kafka topic otlp_logs';

CREATE STREAM IF NOT EXISTS agent_events
(
  event_time         datetime64(3),
  agent              string,    -- claude-code | codex | simulator
  session_id         string,    -- Claude Code session.id / Codex conversation.id
  event              string,    -- tool_result | api_request | sse_event | user_prompt | api_error | ...
  tool_name          string,
  tool_args          string,    -- raw tool input / arguments (JSON)
  call_target        string,    -- normalized: the command, path, or args the call is "about"
  success            bool,
  duration_ms        float64,
  model              string,
  input_tokens       uint64,
  output_tokens      uint64,
  cache_read_tokens  uint64,
  cost_usd           float64,
  error              string,
  attributes         map(string, string)
)
COMMENT 'Normalized agent telemetry (from OpenTelemetry log events)';

CREATE STREAM IF NOT EXISTS agent_session_log
(
  session_id  string,
  agent       string,
  event_type  string,   -- user_prompt | tool_call | control
  content     string
)
COMMENT 'Append-only session log written by the agent''s own hooks';

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
  hint        string    -- handed to the agent as the reason its next tool call was blocked
)
COMMENT 'Decisions fed back to the running agent';
