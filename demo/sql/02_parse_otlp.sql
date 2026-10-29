-- ============================================================================
-- 02_parse_otlp.sql — flatten OTLP/JSON into one row per span
--
-- An OTLP payload nests spans as resourceSpans[] -> scopeSpans[] -> spans[],
-- with attributes as [{key, value: {stringValue|intValue|...}}].
-- This view unnests it and pulls the GenAI semantic-convention attributes
-- into typed columns. It runs continuously: every payload that lands in
-- otlp_raw shows up in agent_spans within milliseconds.
-- ============================================================================

-- OTLP attribute list [{key, value:{stringValue|intValue|...}}] -> map(string, string).
-- stringValue is unescaped; other value types keep their JSON literal.
CREATE FUNCTION IF NOT EXISTS otel_attrs AS (kvs) ->
  map_from_arrays(
    array_map(a -> json_extract_string(a, 'key'), kvs),
    array_map(a -> if(json_has(a, 'value', 'stringValue'),
                      json_extract_string(a, 'value', 'stringValue'),
                      trim(BOTH '"' FROM json_extract_raw(json_extract_raw(a, 'value'), 1))), kvs));

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_otlp_to_spans INTO agent_spans AS
SELECT
  from_unix_timestamp64_nano(to_int64(json_extract_string(sp, 'startTimeUnixNano')))::datetime64(3) AS start_time,
  (to_int64(json_extract_string(sp, 'endTimeUnixNano')) - to_int64(json_extract_string(sp, 'startTimeUnixNano'))) / 1e6 AS duration_ms,
  res_attrs['service.name']                         AS service,
  json_extract_string(sp, 'traceId')                AS trace_id,
  json_extract_string(sp, 'spanId')                 AS span_id,
  json_extract_string(sp, 'parentSpanId')           AS parent_span_id,
  json_extract_string(sp, 'name')                   AS span_name,
  to_int8(json_extract_int(sp, 'status', 'code'))   AS status_code,
  attrs['gen_ai.conversation.id']                   AS session_id,
  attrs['gen_ai.agent.name']                        AS agent_name,
  attrs['gen_ai.operation.name']                    AS operation,
  attrs['gen_ai.request.model']                     AS model,
  attrs['gen_ai.tool.name']                         AS tool_name,
  attrs['gen_ai.tool.call.arguments']               AS tool_args,
  to_uint32_or_zero(attrs['gen_ai.usage.input_tokens'])  AS input_tokens,
  to_uint32_or_zero(attrs['gen_ai.usage.output_tokens']) AS output_tokens,
  attrs                                             AS attributes
FROM
(
  SELECT
    array_join(array_flatten(array_map(
      rs -> array_map(
              sp -> (json_extract_array_raw(rs, 'resource', 'attributes'), sp),
              array_flatten(array_map(ss -> json_extract_array_raw(ss, 'spans'),
                                      json_extract_array_raw(rs, 'scopeSpans')))),
      json_extract_array_raw(raw, 'resourceSpans')))) AS pair,
    pair.2 AS sp,
    otel_attrs(pair.1) AS res_attrs,
    otel_attrs(json_extract_array_raw(sp, 'attributes')) AS attrs
  FROM otlp_raw
);
