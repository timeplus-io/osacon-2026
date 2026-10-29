"""OTLP/JSON log payloads shaped like what Claude Code and Codex export.

Attribute names come from the agents themselves:
  Claude Code (2.1.x): log body `claude_code.<event>`, attributes `event.name`,
    `session.id`, `tool_name`, `success` ("true"/"false"), `duration_ms`,
    `tool_input` (with OTEL_LOG_TOOL_DETAILS=1), `model`, `input_tokens`,
    `output_tokens`, `cache_read_tokens`, `cost_usd`.
  Codex (codex-rs/otel): `event.name` = `codex.tool_result` with `tool_name`,
    `call_id`, `arguments`, `success`, `duration_ms`; `codex.sse_event` with
    `input_token_count`, `output_token_count`; `conversation.id` on every event.
"""

from __future__ import annotations

import json
import time


def _attr(k: str, v) -> dict:
    return {"key": k, "value": {"stringValue": str(v)}}


def logs_payload(service: str, records: list[dict]) -> str:
    """records: [{"body": str, "attrs": {k: v}}] -> ExportLogsServiceRequest as OTLP/JSON."""
    now = time.time_ns()
    return json.dumps({"resourceLogs": [{
        "resource": {"attributes": [_attr("service.name", service)]},
        "scopeLogs": [{"scope": {"name": service}, "logRecords": [
            {"timeUnixNano": str(now + i), "observedTimeUnixNano": str(now + i),
             "body": {"stringValue": r["body"]},
             "attributes": [_attr(k, v) for k, v in r["attrs"].items()]}
            for i, r in enumerate(records)]}],
    }]})


def claude_tool_result(session: str, command: str, ok: bool = True, description: str = "Run it") -> dict:
    return {"body": "claude_code.tool_result", "attrs": {
        "event.name": "tool_result", "session.id": session, "tool_name": "Bash",
        "success": "true" if ok else "false", "duration_ms": "412",
        "tool_input": json.dumps({"command": command, "description": description}),
        **({} if ok else {"error": "Exit code 7"}),
    }}


def claude_api_request(session: str, cost: float, inp: int = 1200, out: int = 300) -> dict:
    return {"body": "claude_code.api_request", "attrs": {
        "event.name": "api_request", "session.id": session, "model": "claude-sonnet",
        "input_tokens": inp, "output_tokens": out, "cache_read_tokens": 18000,
        "cost_usd": cost, "duration_ms": "2300",
    }}


def codex_tool_result(conv: str, cmd: str, ok: bool = True) -> dict:
    return {"body": "", "attrs": {
        "event.name": "codex.tool_result", "conversation.id": conv, "tool_name": "shell",
        "call_id": "call_1", "success": "true" if ok else "false", "duration_ms": "380",
        "arguments": json.dumps({"command": ["bash", "-lc", cmd], "workdir": "/workspace"}),
        "model": "gpt-5-codex",
    }}


def codex_usage(conv: str, inp: int, out: int) -> dict:
    return {"body": "", "attrs": {
        "event.name": "codex.sse_event", "event.kind": "response.completed", "conversation.id": conv,
        "input_token_count": inp, "output_token_count": out, "model": "gpt-5-codex",
    }}
