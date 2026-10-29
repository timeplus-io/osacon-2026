-- ============================================================================
-- 02_parse_otlp_logs.sql — OTLP/JSON log payloads -> one row per agent event
--
-- Claude Code and Codex both export their activity as OpenTelemetry *log
-- events* (Claude Code: `claude_code.tool_result`, `claude_code.api_request`,
-- ...; Codex: `codex.tool_result`, `codex.sse_event`, ...). The Collector
-- writes them to Kafka as OTLP/JSON; this view flattens
-- resourceLogs[] -> scopeLogs[] -> logRecords[] and maps both vocabularies
-- onto one schema, so every detector downstream is agent-agnostic.
-- ============================================================================

-- OTLP attribute list [{key, value:{stringValue|intValue|...}}] -> map(string, string)
CREATE FUNCTION IF NOT EXISTS otel_attrs AS (kvs) ->
  map_from_arrays(
    array_map(a -> json_extract_string(a, 'key'), kvs),
    array_map(a -> if(json_has(a, 'value', 'stringValue'),
                      json_extract_string(a, 'value', 'stringValue'),
                      trim(BOTH '"' FROM json_extract_raw(json_extract_raw(a, 'value'), 1))), kvs));

-- What a tool call is "about", stable across retries: the shell command (minus
-- a leading `sleep N &&`), a file path, or else the raw arguments. Agents vary
-- the free-text `description` on every call, so comparing raw args would miss
-- loops.
CREATE FUNCTION IF NOT EXISTS agent_call_target AS (a) ->
  trim(replace_regexp_all(
    multi_if(
      starts_with(json_extract_raw(a, 'command'), '['), json_extract_string(a, 'command', -1),  -- Codex: ["bash","-lc","..."]
      json_extract_string(a, 'command') != '',      json_extract_string(a, 'command'),          -- Claude Code Bash
      json_extract_string(a, 'cmd') != '',          json_extract_string(a, 'cmd'),              -- Codex exec_command
      json_extract_string(a, 'full_command') != '', json_extract_string(a, 'full_command'),     -- Claude Code tool_parameters
      json_extract_string(a, 'file_path') != '',    json_extract_string(a, 'file_path'),        -- Read / Edit / Write
      json_extract_string(a, 'url') != '',          json_extract_string(a, 'url'),              -- WebFetch
      a),
    'sleep\\s+[0-9.]+[smh]?\\s*(&&|;)\\s*', ''));

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_otlp_logs_to_events INTO agent_events AS
SELECT
  from_unix_timestamp64_nano(to_int64(if(json_extract_string(rec, 'timeUnixNano') NOT IN ('', '0'),
                                         json_extract_string(rec, 'timeUnixNano'),
                                         json_extract_string(rec, 'observedTimeUnixNano'))))::datetime64(3) AS event_time,
  multi_if(starts_with(body, 'claude_code.'), 'claude-code',
           starts_with(name, 'codex.'),       'codex',
           res['service.name'])                                            AS agent,
  if(attrs['session.id'] != '', attrs['session.id'], attrs['conversation.id']) AS session_id,
  replace_regexp_one(if(name != '', name, body), '^(claude_code|codex|simulator)\\.', '') AS event,
  attrs['tool_name']                                                       AS tool_name,
  multi_if(attrs['tool_input'] != '',      attrs['tool_input'],
           attrs['arguments'] != '',       attrs['arguments'],
           attrs['tool_parameters'])                                       AS tool_args,
  if(tool_name != '', agent_call_target(tool_args), '')                    AS call_target,
  attrs['success'] != 'false'                                              AS success,
  to_float64_or_zero(attrs['duration_ms'])                                 AS duration_ms,
  if(attrs['model'] != '', attrs['model'], attrs['slug'])                  AS model,
  to_uint64_or_zero(if(attrs['input_tokens'] != '', attrs['input_tokens'], attrs['input_token_count']))    AS input_tokens,
  to_uint64_or_zero(if(attrs['output_tokens'] != '', attrs['output_tokens'], attrs['output_token_count'])) AS output_tokens,
  to_uint64_or_zero(if(attrs['cache_read_tokens'] != '', attrs['cache_read_tokens'], attrs['cached_token_count'])) AS cache_read_tokens,
  to_float64_or_zero(attrs['cost_usd'])                                    AS cost_usd,
  multi_if(attrs['error'] != '', attrs['error'], attrs['error.message'] != '', attrs['error.message'], attrs['error_type']) AS error,
  attrs                                                                    AS attributes
FROM
(
  SELECT
    array_join(array_flatten(array_map(
      rl -> array_map(
              r -> (json_extract_array_raw(rl, 'resource', 'attributes'), r),
              array_flatten(array_map(sl -> json_extract_array_raw(sl, 'logRecords'),
                                      json_extract_array_raw(rl, 'scopeLogs')))),
      json_extract_array_raw(raw, 'resourceLogs')))) AS pair,
    pair.2 AS rec,
    otel_attrs(pair.1) AS res,
    otel_attrs(json_extract_array_raw(rec, 'attributes')) AS attrs,
    attrs['event.name'] AS name,
    json_extract_string(rec, 'body', 'stringValue') AS body
  FROM otlp_logs_raw
)
WHERE session_id != '';
