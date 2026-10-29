-- ============================================================================
-- 04_policy.sql — turn alerts into actions
--
-- The policy is just SQL. "interrupt" injects a hint into the agent's context
-- and lets it continue; "halt" stops the session. The running agent holds a
-- streaming query on agent_actions filtered to its own session id, so a row
-- written here reaches it immediately — that is the loop closing.
-- ============================================================================

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_policy INTO agent_actions AS
SELECT
  session_id,
  multi_if(detector = 'tool_loop',   'interrupt',
           detector = 'tool_errors', 'interrupt',
           detector = 'token_burn',  'halt',
                                     'log') AS action,
  concat(detector, ': ', detail) AS reason,
  multi_if(detector = 'tool_loop',
             concat('You have called ', evidence, ' four times with the same result. ',
                    'It is not making progress. Change strategy: use a different tool or different arguments.'),
           detector = 'tool_errors',
             'Your last three tool calls failed. Stop retrying the same tool; fall back to another source and answer with what you have.',
           '') AS hint
FROM agent_alerts
WHERE severity IN ('high', 'medium');
