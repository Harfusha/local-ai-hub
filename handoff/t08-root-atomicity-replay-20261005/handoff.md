# T08 atomicity/events/recovery acceptance

Assigned HEAD: `2b33602adef0d030fea66cdcc04ca742c60b2e32`; root HEAD: `7cb4bcdfb6d7736b64cb8bcb895157c48f4eebdf`. Root dirty source identity is defined by per-path SHA256 in receipt.

Command: `python -B -u run_atomicity_replay.py` in `C:\Users\Adam\.codex\worktrees\t08-agent-os\.local-ai-hub\handoff\t08-root-atomicity-replay-20261005`.

Actual result: **142 passed in 40.30s**, exit `0`. Full modules:

- `tests/test_agent_events.py`
- `tests/test_agent_tasks.py`
- `tests/test_agent_verification.py`
- `tests/test_agent_crash_recovery.py`
- `tests/test_agent_state_reliability.py`

[Command/options, actual output, root pre/post SHA256, inherited dirty pre/post SHA256](atomicity-replay-receipt.json). [Exact fault/replay test inventory](fault-replay-test-index.json).

Prior planned acceptance receipt remains current: **110 passed in 50.67s**, full nine-file durability suite, core crash selectors, migration faults and seven memory criteria. Tests overlap; counts are separate suite results, not a distinct-test total.

Root drift: `[]`; prior acceptance drift: `[]`; inherited candidate drift: `[]`. All 40 inherited tracked paths preserved. Own writes: only this handoff directory; no source/test edits or root changes. No new packet needed.

Status remains **review**. Live Agent OS completion is **NOT VERIFIED**; Hub is disabled/retryably blocked. No task duplication or retries. Native candidate receipts are not root-owned/live Agent OS receipts.
