#!/usr/bin/env python3
"""Test stand-in for the OpenTelemetry Collector (otlp receiver -> kafka exporter).

Accepts OTLP/HTTP protobuf on /v1/logs (and /v1/traces, /v1/metrics, which are
accepted and dropped) and produces each log batch as one OTLP/JSON message to
the Kafka topic `otlp_logs` — what the real Collector does with
`exporters.kafka.encoding: otlp_json`. Only used by the tests, where container
images are not available; the docker-compose stack uses the real Collector.
"""

from __future__ import annotations

import argparse
import base64
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from google.protobuf.json_format import MessageToDict
from kafka import KafkaProducer
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import ExportLogsServiceRequest

ID_FIELDS = {"traceId", "spanId"}


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
    a = ap.parse_args()
    producer = KafkaProducer(bootstrap_servers=a.brokers, linger_ms=0)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.path.endswith("/v1/logs"):
                req = ExportLogsServiceRequest()
                req.ParseFromString(body)
                msg = json.dumps(hex_ids(MessageToDict(req, use_integers_for_enums=True)), separators=(",", ":"))
                producer.send("otlp_logs", msg.encode())
                producer.flush()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-protobuf")
            self.end_headers()

        def log_message(self, *args):
            pass

    print(f"mini-collector: OTLP/HTTP :{a.port} -> kafka {a.brokers} topic otlp_logs", flush=True)
    ThreadingHTTPServer(("0.0.0.0", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
