#!/usr/bin/env python3
"""End-to-end test: run every scenario against a live Proton and check the loop closed.

Assumes a Proton server on localhost and a schema applied (scripts/setup.sh).

    python tests/e2e_test.py                    # direct mode (agent -> Proton HTTP ingest)
    python tests/e2e_test.py --mode collector   # agent -> OTLP collector -> Kafka -> Proton
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import uuid
from pathlib import Path

from proton_driver import client

AGENT = Path(__file__).resolve().parent.parent / "agent" / "agent.py"

# scenario -> (expected exit code, detectors that must fire, detectors that must not)
EXPECT = {
    "normal": (0, set(), {"tool_loop", "tool_errors", "token_burn"}),
    "loop":   (0, {"tool_loop"}, {"token_burn"}),
    "flaky":  (0, {"tool_errors"}, {"token_burn"}),
    "burn":   (2, {"token_burn"}, set()),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="direct", choices=["direct", "collector"])
    a = ap.parse_args()
    db = client.Client(host="localhost", port=8463)
    run_id = uuid.uuid4().hex[:6]
    failures = []

    for scenario, (want_rc, must, must_not) in EXPECT.items():
        sid = f"test-{run_id}-{scenario}"
        t0 = time.time()
        proc = subprocess.run([sys.executable, str(AGENT), "--scenario", scenario, "--session-id", sid, "--mode", a.mode],
                              capture_output=True, text=True, timeout=120)
        time.sleep(3)
        fired = {r[0] for r in db.execute(
            "SELECT detector FROM table(agent_alerts) WHERE session_id = %(sid)s", {"sid": sid})}
        actions = db.execute("SELECT action FROM table(agent_actions) WHERE session_id = %(sid)s", {"sid": sid})
        spans = db.execute("SELECT count() FROM table(agent_spans) WHERE session_id = %(sid)s", {"sid": sid})[0][0]
        log_rows = db.execute("SELECT count() FROM table(agent_session_log) WHERE session_id = %(sid)s", {"sid": sid})[0][0]

        problems = []
        if proc.returncode != want_rc:
            problems.append(f"exit code {proc.returncode}, want {want_rc}")
        if not must <= fired:
            problems.append(f"missing detectors {must - fired}")
        if fired & must_not:
            problems.append(f"unexpected detectors {fired & must_not}")
        if must and not actions:
            problems.append("no action reached agent_actions")
        if spans == 0:
            problems.append("no spans parsed")
        if log_rows == 0:
            problems.append("no session log rows")

        status = "PASS" if not problems else "FAIL"
        print(f"{status}  {scenario:<7} {time.time() - t0:5.1f}s  spans={spans:<3} log={log_rows:<3} "
              f"detectors={sorted(fired) or '-'} actions={sorted({r[0] for r in actions}) or '-'}")
        for p in problems:
            print(f"      - {p}")
        if problems:
            failures.append(scenario)
            print(proc.stdout[-2000:], proc.stderr[-2000:])

    print("\nall scenarios passed" if not failures else f"\nFAILED: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
