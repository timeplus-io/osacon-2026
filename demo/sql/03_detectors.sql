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
--   tool_loop    4 identical tool calls in a row (again at 8, 12, 16, ...)
--   tool_errors  3 failed tool calls in a row (again at 6, 9)
--   budget       $__BUDGET_USD__ (cost_usd, Claude Code)  or  __BUDGET_TOKENS__ tokens (input+output);
--                fires again at each further multiple of the budget
--
-- __BUDGET_USD__ / __BUDGET_TOKENS__ are filled in from .env (BUDGET_USD,
-- BUDGET_TOKENS) when the schema is applied; see scripts/apply-sql.sh.
-- ============================================================================


-- D1. Tool-call loop
-- Same tool, same target (command / file / args) 4 times in a row. lags()
-- looks back at this session's previous tool calls; `streak` is how many
-- identical calls in a row this one makes. Fires on the 4th identical call
-- and on every 4th after that (8, 12, 16, ...) for as long as the agent keeps
-- going; the policy turns the third alert into a halt. Firing indefinitely
-- means a policy view started late (the "open loop, then close it" demo)
-- still gets an alert within four calls.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_detect_tool_loop INTO agent_alerts AS
SELECT
  session_id,
  'tool_loop' AS detector,
  'high'      AS severity,
  concat(tool_name, ' called ', to_string(streak), 'x in a row on the same target') AS detail,
  concat(tool_name, ': ', substring(call_target, 1, 200)) AS evidence,
  tool_name,
  call_target AS target
FROM
(
  SELECT
    session_id, tool_name, call_target,
    concat(tool_name, '|', call_target) AS call_key,
    lags(call_key, 1, 100) AS prev,                           -- previous 100 tool calls in this session, newest first
    array_first_index(x -> x != call_key, prev) AS streak     -- 4 = this is the 4th identical call in a row
  FROM agent_events
  WHERE event = 'tool_result'
  PARTITION BY session_id
)
WHERE streak >= 4 AND streak % 4 = 0;


-- D2. Tool error streak
-- Three failed tool calls in a row; again at 6 and 9 if the agent keeps going.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_detect_tool_errors INTO agent_alerts AS
SELECT
  session_id,
  'tool_errors' AS detector,
  'medium'      AS severity,
  concat(to_string(streak), ' failed tool calls in a row, last: ', tool_name) AS detail,
  concat(tool_name, ': ', substring(call_target, 1, 120), if(error != '', concat(' -> ', substring(error, 1, 120)), '')) AS evidence,
  tool_name,
  call_target AS target
FROM
(
  SELECT
    session_id, tool_name, call_target, error,
    to_uint8(NOT success) AS failed,
    lags(failed, 1, 9) AS prev,                               -- padded with 0 (= not failed) at session start
    array_first_index(x -> x = 0, prev) AS streak             -- 3 = third failure in a row
  FROM agent_events
  WHERE event = 'tool_result'
  PARTITION BY session_id
)
WHERE failed = 1 AND streak IN (3, 6, 9);


-- D3. Session budget
-- Running spend per session reaches the budget: $__BUDGET_USD__ (Claude Code
-- reports cost_usd on every model call) or __BUDGET_TOKENS__ input+output
-- tokens (Codex and the simulator report tokens only), whichever comes first.
-- Fires on the call that crosses it, and again at every further multiple
-- (2x, 3x, ...): after a person resumes a halted session, it gets one more
-- budget's worth before the next halt. The running total covers the last
-- 500 model calls of the session.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_detect_budget INTO agent_alerts AS
SELECT
  session_id,
  'budget' AS detector,
  'high'   AS severity,
  concat('session reached ', to_string(to_uint32(level_now)), 'x its budget ($',
         to_string(round(cost_now, 2)), ' of $__BUDGET_USD__, ',
         to_string(tokens_now), ' of __BUDGET_TOKENS__ tokens)') AS detail,
  model AS evidence,
  '' AS tool_name,
  '' AS target
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
    array_sum(prev_cost)             AS cost_before,
    greatest(floor(cost_now / __BUDGET_USD__), floor(tokens_now / __BUDGET_TOKENS__))       AS level_now,
    greatest(floor(cost_before / __BUDGET_USD__), floor(tokens_before / __BUDGET_TOKENS__)) AS level_before
  FROM agent_events
  WHERE input_tokens + output_tokens > 0 OR cost_usd > 0
  PARTITION BY session_id
)
WHERE level_now > level_before;
