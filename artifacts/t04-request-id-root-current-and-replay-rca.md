# T04 request-ID root-current and replay RCA — 2026-10-01

## Root-current preflight

Root: `C:\Users\Adam\.local-ai-hub`, HEAD `98a9a1a7611af574caf20a88620c4aa3eb2e918a`.

Current root `src/local_ai_hub/http_server.py` SHA-256: `CD2998708AFBEE64A22D8027AA86969E9C17A05967CBED8431BEE7A4F8D55FD5`.

The current root already validates the header-derived ID in `Handler.do_POST` (line 2646) with `RecoveryJournal.validate_request_id(self._ensure_trace_request_id())`; `_ensure_trace_request_id` is at line 1124. It runs after authorization and before request-body parsing/policy/dispatch. No production hunk is needed for this root snapshot. Root's dirty `http_server.py` remains untouched.

Prepared root-current handoff patch is test-only: `handoff/t04-request-id-preflight-root-current.patch`, SHA-256 `CD95EABA302CA965DFA36D497AEE8CB93F58978715CFB9388EFA27423200C38B`. It adds one invalid-header test asserting HTTP 400, terminal/nonretryable result, no body read, no journal begin, and no work-order dispatch. Candidate selector passed **1 in 0.32s**. `git apply --check --whitespace=error` against current root passed. Root test slot remains T20-owned; no root test ran.

## Candidate replay failure RCA for T07

Exact combined command:
`python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_t04_request_id_preflight.py tests/test_mutation_replay.py::test_post_journal_failure_prevents_mutation_dispatch tests/test_mutation_replay.py::test_http_retry_replays_outcome_and_rejects_changed_payload tests/test_mutation_replay.py::test_recovery_journal_rejects_invalid_request_ids_before_claim`

Result: **13 passed, 2 failed in 1.05s**.

- `test_post_journal_failure_prevents_mutation_dispatch`, `tests/test_mutation_replay.py:585`: observed submitted work-order despite expected empty list. Its `_UnavailableJournal` has no `lookup` method, so candidate `Handler.do_POST` raises `AttributeError` at `http_server.py:2042`; broad `except Exception: pass` at the journal block swallows it. Route dispatch follows. The test's `begin()` OSError is never reached.
- `test_http_retry_replays_outcome_and_rejects_changed_payload`, assertion at `tests/test_mutation_replay.py:631`: observed all three submissions instead of one. Candidate `Handler.do_POST:2042` calls `RecoveryJournal.lookup(request_id, tenant, path)` without required keyword-only `identity` and `payload_fingerprint`; `RecoveryJournal.lookup` at `resilience.py:263` raises `TypeError`. The broad catch at `http_server.py:2058` swallows it. Candidate then calls `begin` at `http_server.py:2057` without required keyword-only `identity` and `payload`; that also raises `TypeError` and is swallowed. No claim/replay record is created, so each request dispatches.

Direct signature reproduction emitted:

```text
lookup: RecoveryJournal.lookup() missing 2 required keyword-only arguments: 'identity' and 'payload_fingerprint'
begin: RecoveryJournal.begin() missing 2 required keyword-only arguments: 'identity' and 'payload'
```

Both failing selectors use valid `req-1`. The preflight accepts it unchanged; candidate diff adds only validation/import before body parsing. Failure source is candidate journal helper-call mismatch, not request-ID validation semantics. T07 owns replay behavior.

Current root has the repaired call chain: `Handler._claim_recovery` at line 2542 calls `RecoveryJournal.begin(..., identity=identity, payload=payload)` at line 2549; the running-request helper call supplies `identity` and `payload_fingerprint` around line 2591. Root current already addresses this candidate-only mismatch. T20 owns root integration and tests.
