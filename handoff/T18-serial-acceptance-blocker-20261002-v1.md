# T18 serial acceptance blocker — 2026-10-02

## Concrete T18 acceptance already delivered

Candidate worktree `C:\Users\Adam\.codex\worktrees\t18-status-dashboard\.local-ai-hub`, HEAD `a1b04bb3bf88dc26a4d17409baf4ae6e2845018f`.

- `local_ai_status(action="full")` candidate now exposes `success` derived from `hub_online`. The broker-routed FastMCP regression passed: one test, `1 passed in 4.18s`, exit 0. Receipt request `req_fd1284f2e240`, execution `18ce318e1fbb49fcb3985890b85b384e`. Exact pins and limitation are in `T18-resume-checkpoint-20261002-v15.md`.
- Existing candidate dashboard/status/telemetry receipts: 42 passed / 18.85s, 65 passed / 22.74s, dashboard supplemental 5 passed / 0.61s, status supplemental 6 passed / 0.69s. Exact command records: `T18-resume-checkpoint-20261002-v7.md`, `T18-status-dashboard-telemetry-acceptance-20261001-v4.md`, `T18-coverage-review-20261002-v1.md`.
- Current scoped `git diff --check` exited 0 across status, dashboard, telemetry and focused test paths. Git emitted one LF-to-CRLF warning for `telemetry.py`.

## Exact next candidate test

T18 telemetry report byte-budget cursor regression remains untested:

```text
python -B -m pytest -q -p no:cacheprovider --tb=short tests/test_telemetry_report_bounds_t18.py::test_report_budget_truncation_advances_cursor_after_retained_rows
```

Pins: `src/local_ai_hub/telemetry.py` SHA-256 `B58636B4FDD994279C5BA2659A80FCF87D4C7233AF3D7337FB7CCB1685D5E338`; `tests/test_telemetry_report_bounds_t18.py` SHA-256 `69C915E4A668F45C6C19353C35134E6F937F850A74A819489DA74F9394A543D0`.

Static source/test review: `_bound_telemetry_report` trims a prefix of `error_fingerprints`, recomputes `next_cursor` from the last retained row, and marks more rows available. The regression asserts cursor tuple matches that retained row. No source-level mismatch found; selector remains necessary for behavioral acceptance.

## Blocker and boundary

User gate: run tests only after T20 serial GO. Latest persisted T18 acceptance matrix records no slot assigned to T18. Current read-only T20 thread status attempts failed with `Unavailable or failed hosts: durable`. Read-only T20 root receipts `artifacts/handoff/T20-t19-release-tests-root-integration-receipt-20261002.json`, `T20-t19-prompts-root-current-receipt-20261002.json`, and `T20-t03-accounting-root-integration-receipt-20261002.json` each report tests not run while T02 holds the exclusive slot. No fresh T18 slot assignment exists. A user-authorized status message to T20 was attempted once; the tool returned `no rollout found for thread id`, so no message was delivered. Do not run this or another selector until T20 gives serial GO for these exact pins.

Root-current trace/dashboard and telemetry deltas are prepared handoff artifacts only. T20 must review/integrate them and own root acceptance. T13 operational-mode/auth/supervisor hunks remain outside T18 edits. No root files, foreign dashboard files, or `/api/context/pack` were changed. No full release or live HTTP recovery claim.
