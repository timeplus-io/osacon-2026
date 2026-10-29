"""The two Proton touch points the agent runtime has besides telemetry:

  SessionLog       appends to the `agent_session_log` stream (HTTP ingest)
  ActionListener   holds a streaming query on `agent_actions` for this session
                   (native protocol, proton-driver) and hands actions to the agent
"""

from __future__ import annotations

import queue
import threading
import time

import requests
from proton_driver import client as proton_client


class SessionLog:
    def __init__(self, proton_http: str, session_id: str):
        self._url = f"{proton_http.rstrip('/')}/proton/v1/ingest/streams/agent_session_log"
        self._session_id = session_id
        self._seq = 0
        self._http = requests.Session()

    def append(self, event_type: str, content: str) -> None:
        self._seq += 1
        body = {
            "columns": ["session_id", "seq", "event_type", "content"],
            "data": [[self._session_id, self._seq, event_type, content]],
        }
        try:
            self._http.post(self._url, json=body, timeout=5).raise_for_status()
        except requests.RequestException as exc:  # the log must never take the agent down
            print(f"  (session log write failed: {exc})")


class ActionListener(threading.Thread):
    """Streaming query: SELECT ... FROM agent_actions WHERE session_id = <me>.

    Proton pushes each new matching row as soon as it is written, so there is
    no polling interval to tune. Actions land on `self.actions` with the
    wall-clock time they arrived.
    """

    def __init__(self, host: str, port: int, session_id: str):
        super().__init__(daemon=True)
        self.actions: "queue.Queue[dict]" = queue.Queue()
        self.ready = threading.Event()
        self._host, self._port, self._session_id = host, port, session_id

    def run(self) -> None:
        while True:
            try:
                c = proton_client.Client(host=self._host, port=self._port)
                rows = c.execute_iter(
                    "SELECT action, reason, hint FROM agent_actions WHERE session_id = %(sid)s",
                    {"sid": self._session_id},
                )
                self.ready.set()
                for action, reason, hint in rows:
                    self.actions.put({"action": action, "reason": reason, "hint": hint, "received_at": time.time()})
            except Exception as exc:  # reconnect; keep the agent running
                print(f"  (action listener reconnecting: {exc})")
                time.sleep(1)

    def poll(self) -> list[dict]:
        out = []
        while True:
            try:
                out.append(self.actions.get_nowait())
            except queue.Empty:
                return out
