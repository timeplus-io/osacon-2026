-- ============================================================================
-- 03_detectors.sql — always-on detectors, written as streaming SQL
--
-- Each detector is a materialized view: it runs continuously, keeps its own
-- state per session, and appends a row to agent_alerts the moment the
-- condition becomes true. No polling, no batch job.
-- ============================================================================


-- D1. Tool-call loop
-- The same tool called with identical arguments 4 times in a row within a
-- session. PARTITION BY gives each session its own state; lags() looks back
-- at that session's previous tool calls. Fires once per streak (on the 4th
-- identical call), not on every call after it.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_detect_tool_loop INTO agent_alerts AS
SELECT
  session_id,
  'tool_loop' AS detector,
  'high'      AS severity,
  concat(tool_name, ' called 4x in a row with identical arguments') AS detail,
  concat(tool_name, '(', tool_args, ')') AS evidence
FROM
(
  SELECT
    session_id, tool_name, tool_args,
    concat(tool_name, '|', tool_args) AS call_key,
    lags(call_key, 1, 4) AS prev            -- previous 4 calls in this session, newest first
  FROM agent_spans
  WHERE operation = 'execute_tool'
  PARTITION BY session_id
)
WHERE array_count(x -> x = call_key, array_slice(prev, 1, 3)) = 3
  AND prev[4] != call_key;


-- D2. Tool error streak
-- Three consecutive failed tool calls in a session (OTLP status code 2).
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_detect_tool_errors INTO agent_alerts AS
SELECT
  session_id,
  'tool_errors' AS detector,
  'medium'      AS severity,
  concat('3 consecutive tool failures, last: ', tool_name) AS detail,
  error_type AS evidence
FROM
(
  SELECT
    session_id, tool_name, status_code,
    attributes['error.type'] AS error_type,
    lags(status_code, 1, 3) AS prev
  FROM agent_spans
  WHERE operation = 'execute_tool'
  PARTITION BY session_id
)
WHERE status_code = 2
  AND prev[1] = 2 AND prev[2] = 2
  AND prev[3] != 2;


-- D3. Token burn
-- The last 5 model calls in a session consumed more than 20,000 tokens —
-- runaway context growth, or a model stuck "thinking". Row-based per session
-- (no time window to wait out), and it fires once, on the call that crosses
-- the line: the sum over the last 5 calls is above the limit, and the sum over
-- the 5 calls before this one was not.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_detect_token_burn INTO agent_alerts AS
SELECT
  session_id,
  'token_burn' AS detector,
  'high'       AS severity,
  concat(to_string(burn_now), ' tokens across the last 5 model calls (limit 20000)') AS detail,
  model AS evidence
FROM
(
  SELECT
    session_id, model,
    input_tokens + output_tokens AS tokens,
    lags(tokens, 1, 5) AS prev,                         -- this session's previous 5 calls
    tokens + array_sum(array_slice(prev, 1, 4)) AS burn_now,
    array_sum(prev) AS burn_before
  FROM agent_spans
  WHERE operation = 'chat'
  PARTITION BY session_id
)
WHERE burn_now > 20000 AND burn_before <= 20000;
