# CLAUDE.md

Read **HANDOVER.md** first: it covers the current state, the design (detection runs asynchronously, enforcement synchronously; decisions are aimed at one call, expire, escalate, and can be resumed), how to run and test, and what is still unverified.

- Talk deadline: OSA Con, Mon Nov 2, 2026. The content must be open source only, with nothing confidential on screen.
- The SQL on slides 8 and 9 mirrors `demo/sql/03_detectors.sql` and `demo/sql/04_policy.sql`. Flag any change to those files so the deck can be updated.
- Tests: `python3 demo/tests/e2e_test.py --kafka localhost:9092 --otlp http://localhost:4318` (needs Proton, Kafka and `tests/mini_collector.py`; see HANDOVER §3). Every behaviour change needs a check there.
- The hook (`demo/hooks/proton_gate.py`) is stdlib-only Python and must fail open.
