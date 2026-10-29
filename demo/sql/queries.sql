-- ============================================================================
-- queries.sql — what to run live (Grafana shows the same; this is the terminal view)
-- Open a SQL shell:  docker compose exec proton proton client
-- Streaming queries run until Ctrl-C; table(...) queries are one-shot history.
-- ============================================================================


-- Q1. Live tail: every tool call from every agent, as it happens
SELECT _tp_time, agent, session_id, tool_name, call_target, success
FROM agent_events
WHERE event = 'tool_result';


-- Q2. Model spend per session, live (Claude Code reports cost; Codex reports tokens)
SELECT session_id, any(agent) AS agent,
       sum(input_tokens + output_tokens) AS total_tokens,
       round(sum(cost_usd), 3)           AS total_cost_usd
FROM agent_events
WHERE input_tokens + output_tokens > 0 OR cost_usd > 0
GROUP BY session_id
EMIT PERIODIC 2s;


-- Q3. Decisions going back to agents
SELECT _tp_time, session_id, action, reason FROM agent_actions;


-- Q4. Enrich: each alert joined with what the user actually asked
--     (stream-to-stream join with the session log the hooks write; the two
--     rows must be within 2 minutes of each other — Proton caps the join range)
SELECT a.session_id, a.detector, a.detail, g.content AS user_prompt
FROM agent_alerts AS a
INNER JOIN agent_session_log AS g
  ON a.session_id = g.session_id AND date_diff_within(2m)
WHERE g.event_type = 'user_prompt';


-- Q5. Replay one session from its log (history)
SELECT _tp_time, event_type, substring(content, 1, 140) AS content
FROM table(agent_session_log)
WHERE session_id = 'REPLACE_ME'
ORDER BY _tp_time;


-- Q6. Post-mortem: which detectors fired, across all sessions and agents
SELECT e.agent, a.detector, count() AS alerts
FROM table(agent_alerts) AS a
INNER JOIN (SELECT DISTINCT session_id, agent FROM table(agent_events)) AS e
  ON a.session_id = e.session_id
GROUP BY e.agent, a.detector
ORDER BY alerts DESC;


-- Q7. Debug: the raw OTLP payloads as they come off Kafka
SELECT substring(raw, 1, 400) FROM otlp_logs_raw;
