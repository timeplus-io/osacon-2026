-- ============================================================================
-- queries.sql — what to run live on stage (one per terminal pane)
-- Open a SQL shell:  docker compose exec proton proton client
-- Streaming queries run until Ctrl-C; table(...) queries are one-shot history.
-- ============================================================================


-- Q1. Live tail: every span, the moment it arrives
SELECT start_time, session_id, operation,
       if(tool_name != '', tool_name, model) AS what,
       round(duration_ms) AS ms, status_code,
       input_tokens + output_tokens AS tokens
FROM agent_spans;


-- Q2. Per-session activity in 5-second windows
SELECT window_start, session_id,
       count_if(operation = 'execute_tool') AS tool_calls,
       count_if(status_code = 2)            AS errors,
       sum(input_tokens + output_tokens)    AS tokens
FROM tumble(agent_spans, 5s)
GROUP BY window_start, session_id;


-- Q3. Decisions going back to agents
SELECT _tp_time, session_id, action, reason FROM agent_actions;


-- Q4. Enrich: each alert joined with what the user actually asked
--     (stream-to-stream join over the agent's own session log)
SELECT a.session_id, a.detector, a.detail, g.content AS user_goal
FROM agent_alerts AS a
INNER JOIN agent_session_log AS g
  ON a.session_id = g.session_id AND date_diff_within(2m)
WHERE g.event_type = 'user_goal';


-- Q5. Replay one session from its append-only log (history)
SELECT seq, event_type, substring(content, 1, 120) AS content
FROM table(agent_session_log)
WHERE session_id = 'REPLACE_ME'
ORDER BY seq;


-- Q6. Post-mortem: which detectors fired, across all sessions so far
SELECT detector, count() AS alerts, uniq_exact(session_id) AS sessions
FROM table(agent_alerts)
GROUP BY detector
ORDER BY alerts DESC;


-- Q7. Closed-loop latency: from the span that completed the pattern to the action
--     (approximate: alert time minus the latest tool span of that session before it)
SELECT a.session_id, a.detector,
       date_diff('ms', max(s._tp_time), any(a._tp_time)) AS detect_ms
FROM table(agent_alerts) AS a
INNER JOIN table(agent_spans) AS s ON a.session_id = s.session_id
WHERE s.operation = 'execute_tool' AND s._tp_time <= a._tp_time
GROUP BY a.session_id, a.detector, a._tp_time
ORDER BY any(a._tp_time) DESC
LIMIT 10;
