#!/usr/bin/env python3
"""Test stand-in for the OpenTelemetry Collector (otlp receiver -> kafka exporter).

Accepts OTLP/HTTP protobuf on /v1/traces and produces one OTLP/JSON message per
request to a Kafka topic — the same thing the real Collector does with
`exporters.kafka.encoding: otlp_json`. Used by the e2e test where container
images are not available; the docker-compose stack uses the real Collector.
"""

from __future__ import annotations

import argparse
import base64
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from google.protobuf.json_format import MessageToDict
from kafka import KafkaProducer
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

ID_FIELDS = {"traceId", "spanId", "parentSpanId"}


def hex_ids(node):
    if isinstance(node, dict):
        return {k: (base64.b64decode(v).hex() if k in ID_FIELDS and isinstance(v, str) else hex_ids(v)) for k, v in node.items()}
    if isinstance(node, list):
        return [hex_ids(v) for v in node]
    return node


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=4318)
    ap.add_argument("--brokers", default="localhost:9092")
    ap.add_argument("--topic", default="otlp_spans")
    a = ap.parse_args()
    producer = KafkaProducer(bootstrap_servers=a.brokers, linger_ms=0)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            req = ExportTraceServiceRequest()
            req.ParseFromString(body)
            msg = json.dumps(hex_ids(MessageToDict(req, use_integers_for_enums=True)), separators=(",", ":"))
            producer.send(a.topic, msg.encode())
            producer.flush()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-protobuf")
            self.end_headers()

        def log_message(self, *args):
            pass

    print(f"mini-collector: OTLP/HTTP :{a.port} -> kafka {a.brokers} topic {a.topic}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
