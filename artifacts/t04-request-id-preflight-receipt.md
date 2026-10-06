# T04 request-ID preflight receipt — 2026-10-01

Candidate worktree: `C:\Users\Adam\.codex\worktrees\t04-integration\.local-ai-hub`.

Candidate HEAD: `3658d5056354849ddf17883ed04f807f16cc44c1`. Root HEAD was not changed by this work.

## Change

`src/local_ai_hub/http_server.py` now validates the trace/request ID with `RecoveryJournal.validate_request_id()` after authorization and before reading the POST body, journal lookup/begin, or route dispatch. Invalid IDs return HTTP 400 with `terminal=true`, `retryable=false`; authorization still takes precedence. JSON-body `request_id` cannot replace the header ID used for replay identity. During root integration, keep this guard before T13's operational-mode gate.

Added `tests/test_t04_request_id_preflight.py` covering whitespace and overlength header IDs, no body read/journal/dispatch, authorization precedence, and conflicting body/header IDs. No T13 mode-route code changed. The only other `http_server.py` hunks are earlier T04 SSE work; preserve them separately during integration.

## Validation

RED command: `python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t04_request_id_preflight.py` — **2 expected failures, 2 passed**. Both invalid IDs incorrectly reached route dispatch and returned HTTP 200.

GREEN command: same command after the guard — **4 passed in 0.27s**.

Adjacent replay/journal check:
`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t04_request_id_preflight.py tests/test_mutation_replay.py::test_post_journal_failure_prevents_mutation_dispatch tests/test_mutation_replay.py::test_http_retry_replays_outcome_and_rejects_changed_payload tests/test_mutation_replay.py::test_recovery_journal_rejects_invalid_request_ids_before_claim`

Result: **13 passed, 2 failed in 1.05s**. The two failures were `test_post_journal_failure_prevents_mutation_dispatch` and `test_http_retry_replays_outcome_and_rejects_changed_payload`, both in adjacent replay behavior. They exercise valid `req-1` IDs and routes outside the new invalid-ID preflight; no replay semantics were changed here. T07 owns replay integration; these failures remain open for owner review.

`git diff --check` passes for the request-ID implementation, focused test, and receipts. Root source/tests were not edited. HUB was not used.

Current-root and replay RCA, including exact helper signature mismatch and a test-only root-current patch, is recorded in `artifacts/t04-request-id-root-current-and-replay-rca.md`. The current root HTTP source SHA-256 is `CD2998708AFBEE64A22D8027AA86969E9C17A05967CBED8431BEE7A4F8D55FD5`; its preflight guard is already present. T20 retains root test ownership.
