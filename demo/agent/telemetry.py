"""OpenTelemetry setup for the demo agent.

Two export paths, same wire format (OTLP/JSON) and same downstream SQL:

  collector  OTLP/HTTP -> OpenTelemetry Collector -> kafka exporter (otlp_json)
             -> Kafka topic `otlp_spans` -> Proton external stream -> otlp_raw
  direct     the agent POSTs OTLP/JSON straight into Proton's `otlp_raw` stream
             through the HTTP ingest API (no collector, no Kafka — handy offline)
"""

from __future__ import annotations

import base64
import json
from typing import Sequence

import requests
from google.protobuf.json_format import MessageToDict
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult

_ID_FIELDS = {"traceId", "spanId", "parentSpanId"}


def _b64_ids_to_hex(node):
    """protobuf JSON renders bytes as base64; OTLP/JSON wants hex trace/span ids (and integer enums)."""
    if isinstance(node, dict):
        return {
            k: (base64.b64decode(v).hex() if k in _ID_FIELDS and isinstance(v, str) else _b64_ids_to_hex(v))
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [_b64_ids_to_hex(v) for v in node]
    return node


def spans_to_otlp_json(spans: Sequence[ReadableSpan]) -> str:
    """Encode spans exactly as the Collector's kafka exporter does with `encoding: otlp_json`."""
    request = encode_spans(spans)
    return json.dumps(_b64_ids_to_hex(MessageToDict(request, use_integers_for_enums=True)), separators=(",", ":"))


class ProtonOtlpJsonExporter(SpanExporter):
    """Ships each batch as one OTLP/JSON row into Proton's `otlp_raw` stream."""

    def __init__(self, proton_http: str, stream: str = "otlp_raw"):
        self._url = f"{proton_http.rstrip('/')}/proton/v1/ingest/streams/{stream}"
        self._session = requests.Session()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        body = {"columns": ["raw"], "data": [[spans_to_otlp_json(spans)]]}
        try:
            resp = self._session.post(self._url, json=body, timeout=5)
            resp.raise_for_status()
            return SpanExportResult.SUCCESS
        except requests.RequestException:
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        self._session.close()


def setup_tracing(service_name: str, mode: str, proton_http: str, otlp_endpoint: str) -> TracerProvider:
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if mode == "collector":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter: SpanExporter = OTLPSpanExporter(endpoint=f"{otlp_endpoint.rstrip('/')}/v1/traces")
    else:
        exporter = ProtonOtlpJsonExporter(proton_http)
    # short delay: the whole point is seconds, not minutes
    provider.add_span_processor(BatchSpanProcessor(exporter, schedule_delay_millis=200, max_export_batch_size=64))
    trace.set_tracer_provider(provider)
    return provider
