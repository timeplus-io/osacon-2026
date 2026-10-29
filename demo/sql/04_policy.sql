-- ============================================================================
-- 04_policy.sql — turn alerts into actions
--
-- The policy is just SQL. The agent's PreToolUse hook (hooks/proton_gate.py)
-- reads agent_actions for its session before every tool call:
--   interrupt  the next tool call is blocked and `hint` is handed to the model
--              as the reason — it reads it like any tool result and adapts
--   halt       tool calls are blocked and the session is stopped
-- ============================================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_policy INTO agent_actions AS
SELECT
  session_id,
  multi_if(detector = 'tool_loop',   'interrupt',
           detector = 'tool_errors', 'interrupt',
           detector = 'budget',      'halt',
                                     'log') AS action,
  concat(detector, ': ', detail) AS reason,
  multi_if(detector = 'tool_loop',
             concat('[stream policy] You have repeated the same tool call four times with no new result (',
                    evidence, '). Repeating it again will not help. Stop and change approach: ',
                    'tell the user what you observed, or investigate a different way.'),
           detector = 'tool_errors',
             concat('[stream policy] Your last three tool calls failed (', evidence, '). ',
                    'Stop retrying the same operation. Look for an alternative source in the workspace, ',
                    'or report the failure to the user.'),
           detector = 'budget',
             concat('[stream policy] This session has exhausted its budget (', detail, '). ',
                    'Do not call any more tools. Summarize what you have done so far for the user and stop.'),
           '') AS hint
FROM agent_alerts
WHERE severity IN ('high', 'medium');
