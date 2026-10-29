-- ============================================================================
-- 03_detectors.sql — always-on detectors, written as streaming SQL
--
-- Each detector is a materialized view over agent_events: it runs
-- continuously, keeps its own state per session (PARTITION BY session_id),
-- and appends one row to agent_alerts the moment its condition becomes true.
-- They don't know or care whether the agent is Claude Code, Codex, or the
-- simulator.
--
-- Thresholds (edit here, then scripts/reset.sh):
--   tool_loop    4 identical tool calls in a row
--   tool_errors  3 failed tool calls in a row
--   budget       $__BUDGET_USD__ (cost_usd, Claude Code)  or  __BUDGET_TOKENS__ tokens (input+output)
--
-- __BUDGET_USD__ / __BUDGET_TOKENS__ are filled in from .env (BUDGET_USD,
-- BUDGET_TOKENS) when the schema is applied; see scripts/apply-sql.sh.
-- ============================================================================


-- D1. Tool-call loop
-- Same tool, same target (command / file / args) 4 times in a row. lags()
-- looks back at this session's previous tool calls; fires once per streak,
-- on the 4th identical call.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_detect_tool_loop INTO agent_alerts AS
SELECT
  session_id,
  'tool_loop' AS detector,
  'high'      AS severity,
  concat(tool_name, ' called 4x in a row on the same target') AS detail,
  concat(tool_name, ': ', substring(call_target, 1, 200)) AS evidence
FROM
(
  SELECT
    session_id, tool_name, call_target,
    concat(tool_name, '|', call_target) AS call_key,
    lags(call_key, 1, 4) AS prev            -- previous 4 tool calls in this session, newest first
  FROM agent_events
  WHERE event = 'tool_result'
  PARTITION BY session_id
)
WHERE array_count(x -> x = call_key, array_slice(prev, 1, 3)) = 3
  AND prev[4] != call_key;


-- D2. Tool error streak
-- Three failed tool calls in a row.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_detect_tool_errors INTO agent_alerts AS
SELECT
  session_id,
  'tool_errors' AS detector,
  'medium'      AS severity,
  concat('3 failed tool calls in a row, last: ', tool_name) AS detail,
  concat(tool_name, ': ', substring(call_target, 1, 120), if(error != '', concat(' -> ', substring(error, 1, 120)), '')) AS evidence
FROM
(
  SELECT
    session_id, tool_name, call_target, error,
    to_uint8(NOT success) AS failed,
    lags(failed, 1, 3) AS prev              -- padded with 0 (= not failed) at session start
  FROM agent_events
  WHERE event = 'tool_result'
  PARTITION BY session_id
)
WHERE failed = 1
  AND prev[1] = 1 AND prev[2] = 1
  AND prev[3] = 0;


-- D3. Session budget
-- Running spend per session crosses the budget: $__BUDGET_USD__ (Claude Code
-- reports cost_usd on every model call) or __BUDGET_TOKENS__ input+output
-- tokens (Codex and the simulator report tokens only). Fires once, on the call that crosses it.
-- The running total covers the last 500 model calls of the session.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_detect_budget INTO agent_alerts AS
SELECT
  session_id,
  'budget' AS detector,
  'high'   AS severity,
  if(cost_now > __BUDGET_USD__,
     concat('session spend $', to_string(round(cost_now, 2)), ' crossed the $__BUDGET_USD__ budget'),
     concat('session used ', to_string(tokens_now), ' tokens, crossing the __BUDGET_TOKENS__ budget')) AS detail,
  model AS evidence
FROM
(
  SELECT
    session_id, model,
    input_tokens + output_tokens AS tokens,
    lags(tokens, 1, 500)   AS prev_tokens,
    lags(cost_usd, 1, 500) AS prev_cost,
    tokens + array_sum(prev_tokens)  AS tokens_now,
    array_sum(prev_tokens)           AS tokens_before,
    cost_usd + array_sum(prev_cost)  AS cost_now,
    array_sum(prev_cost)             AS cost_before
  FROM agent_events
  WHERE input_tokens + output_tokens > 0 OR cost_usd > 0
  PARTITION BY session_id
)
WHERE (cost_now > __BUDGET_USD__ AND cost_before <= __BUDGET_USD__)
   OR (tokens_now > __BUDGET_TOKENS__ AND tokens_before <= __BUDGET_TOKENS__ AND cost_now <= __BUDGET_USD__);
