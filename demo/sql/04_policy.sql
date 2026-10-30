-- ============================================================================
-- 04_policy.sql — turn alerts into actions
--
-- The policy is just SQL. The agent's PreToolUse hook (hooks/proton_gate.py)
-- looks up agent_actions for its session before every tool call:
--   interrupt  aimed at one call (tool_name + target): if the agent tries that
--              call again within the next minute it is blocked once, and `hint`
--              is handed to the model as the reason. Any other call runs.
--   halt       every tool call is blocked and the session is stopped, until a
--              person resumes it ('[resume]' in a prompt, or scripts/resume.sh).
--
-- Escalation: the third failing pattern in a row (loop / error streak) in the
-- same session is a halt, not another interrupt — two hints didn't work. With
-- the detectors re-firing as a streak grows, an agent that ignores the hint
-- is halted at the 12th identical call (or 9th failure). Only alerts handled
-- *live* (within 2 s of being raised) count as hints the agent could have
-- seen: when a paused view is resumed and replays a backlog, every replayed
-- alert still becomes an interrupt, but the backlog does not add up to a halt.
--
-- SYSTEM PAUSE MATERIALIZED VIEW mv_policy and the stream is observability
-- only: alerts still fire, no decision reaches the agent. SYSTEM RESUME replays
-- the alerts that fired while paused (each becomes a decision now) and carries
-- on live (scripts/policy.sh off|on).
-- ============================================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_policy INTO agent_actions AS
SELECT
  session_id,
  multi_if(detector = 'budget', 'halt',
           escalate,            'halt',
           is_pattern,          'interrupt',
                                'log') AS action,
  concat(detector, ': ', detail, if(escalate, ' (third failing pattern this session)', ''),
         if(live, '', ' (replayed)')) AS reason,   -- `live` must be projected here: see the note above the subquery
  multi_if(escalate,
             concat('[stream policy] This session has now hit a failing pattern three times (latest: ', evidence, '). ',
                    'Stopping here so a person can take a look. Do not call any more tools; ',
                    'summarize what you tried for the user.'),
           detector = 'tool_loop',
             concat('[stream policy] You have repeated the same tool call with no new result: ', detail, ' (',
                    evidence, '). Repeating it again will not help. Stop and change approach: ',
                    'tell the user what you observed, or investigate a different way.'),
           detector = 'tool_errors',
             concat('[stream policy] Your recent tool calls keep failing: ', detail, ' (', evidence, '). ',
                    'Stop retrying the same operation. Look for an alternative source in the workspace, ',
                    'or report the failure to the user.'),
           detector = 'budget',
             concat('[stream policy] This session has exhausted its budget (', detail, '). ',
                    'Do not call any more tools. Summarize what you have done so far for the user and stop.'),
           '') AS hint,
  detector,
  tool_name,
  if(action = 'interrupt', alert_target, '') AS target
FROM
(
  SELECT
    session_id, detector, detail, evidence, tool_name, target AS alert_target,
    detector IN ('tool_loop', 'tool_errors') AS is_pattern,
    -- Proton 3.0.x: an alias that is used only inside lags() is not evaluated per
    -- row in a materialized view (it came out constant false). Projecting `live` in
    -- the outer SELECT (the '(replayed)' tag in `reason`) makes it a real column.
    date_diff('millisecond', _tp_time, now64(3)) < 2000 AS live,   -- handled as it happened, not replayed
    lags(if(is_pattern AND live, detector, ''), 1, 2) AS prev,       -- this session's previous two live hints
    is_pattern AND prev[1] != '' AND prev[2] != '' AS escalate
  FROM agent_alerts
  WHERE severity IN ('high', 'medium')
  PARTITION BY session_id
);
