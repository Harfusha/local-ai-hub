# Application Audit and Hardening Implementation Plan

> **For agentic workers:** Execute each task in order, keeping the verification gate for that task green before moving on. Do not commit or push automatically; the user requested an in-place repair workflow.

**Goal:** Find and repair reproducible correctness, dashboard, performance, and operational defects across Local AI Hub, with regression coverage and a clean release gate.

**Architecture:** Start from deterministic repository evidence and existing tests. Repair one bounded subsystem at a time: async orchestration, dashboard/API behavior, command/security boundaries, then performance and operational checks. Preserve the compact MCP surface and current configuration policy; avoid speculative refactors.

**Tech Stack:** Python 3.11+, embedded dashboard JavaScript/CSS in `src/local_ai_hub/dashboard.py`, HTTP service, SQLite-backed Agent OS state, pytest, Node dashboard checker.

**Spec:** User request: inspect the application, find bugs and unoptimized parts, find dashboard problems, and fix all reproducible issues.

## Global Constraints

- Do not commit, push, reset, or discard user changes.
- Keep runtime state under the configured `server.state_dir`; do not add generated state to the repository.
- Preserve the compact public MCP surface.
- Deterministic/indexed evidence precedes semantic suggestions; do not implement findings that cannot be reproduced or tied to source evidence.
- Every code change gets a focused regression test and the relevant dashboard/selftest checks.
- Use the project interpreter: `.venv\\Scripts\\python.exe`; system Python does not contain `mcp`.

## Review Focus

- Async recovery must not race between terminal job state and trace reopening; pin the ordering with a deterministic test.
- Dashboard polling and event-stream reconnects must not leave stale status, duplicate timers, or stuck loading controls.
- Dashboard-generated HTML must escape repository/model/command data before insertion into `innerHTML`.
- API failures and timeouts must restore button state and expose an actionable error without corrupting the current view.
- Long-running repository scans must remain bounded and must not grow DOM/state without limits.

---

### Task 1: Baseline and evidence ledger

**Files:**
- Inspect: `src/local_ai_hub/async_jobs.py`, `src/local_ai_hub/app.py`, `src/local_ai_hub/services.py`, `src/local_ai_hub/dashboard.py`, `src/local_ai_hub/commands.py`
- Test: `tests/test_async_jobs.py`, `tests/test_dashboard_operational_surfaces.py`, `tests/test_dashboard_custom_modals.py`, `tests/test_stuck_preprocessing_and_dashboard_fixes.py`

**Interfaces:**
- Consume the current checkout at `91bde1d` and existing test fixtures.
- Produce a short evidence list in the task checkpoint: each candidate needs file/symbol, reproduction command, observed result, and planned owner task.

- [ ] Run the focused dashboard suite and `python tools/check_dashboard.py` with `.venv\\Scripts\\python.exe` where applicable.
- [ ] Reproduce `tests/test_async_jobs.py::test_recovered_async_job_reopens_terminal_trace` at least three isolated times; record whether the earlier `done` versus `queued` mismatch is deterministic or flaky.
- [ ] Run `local_ai_repo(action="security_audit")`, `complexity`, and `audit_dependencies`; classify test-fixture false positives separately from production findings.
- [ ] Do not edit code in this task; reject any finding without a source location and a repeatable check.

### Task 2: Async orchestration correctness

**Files:**
- Modify only the async lifecycle owner identified by the failing test, expected candidates `src/local_ai_hub/async_jobs.py` and `src/local_ai_hub/app.py`.
- Test: `tests/test_async_jobs.py`.

**Interfaces:**
- Preserve `AsyncJobManager` public methods and existing `DebugTraceStore` lifecycle calls.
- The recovery path must leave a terminal job in the expected trace state before returning from recovery.

- [ ] Add or tighten one regression test around the exact observed ordering; use a controlled event/barrier rather than `sleep`.
- [ ] Run the new test once and confirm it fails against the current implementation if the race is reproducible.
- [ ] Implement the smallest ordering/state-transition fix; do not alter model scheduling behavior unrelated to recovery.
- [ ] Run the new regression, all `tests/test_async_jobs.py`, and the existing async tests that cover cancellation, timeout, and restart recovery.

### Task 3: Dashboard state and API failure handling

**Files:**
- Modify: `src/local_ai_hub/dashboard.py` only at the affected rendering, polling, stream-reconnect, or modal handlers.
- Test: `tests/test_dashboard_operational_surfaces.py`, `tests/test_dashboard_custom_modals.py`, `tests/test_stuck_preprocessing_and_dashboard_fixes.py`; add a focused test beside the owning suite.

**Interfaces:**
- Preserve the existing dashboard DOM IDs and `/api/*` routes.
- Preserve `apiFetch`/`post` authentication and timeout behavior.

- [ ] Use the existing dashboard checker and tests to locate a real stale-state or failure-state gap; do not rewrite inline CSS or split the large file as a cosmetic refactor.
- [ ] Add a regression fixture for the exact failure response: button disabled state, status text, retry/reconnect behavior, and rendered error must all settle.
- [ ] Escape every newly affected dynamic value before `innerHTML`; prefer existing `esc()` and text nodes when the value is plain text.
- [ ] Run `python tools/check_dashboard.py` and all dashboard suites after the fix.

### Task 4: Command/API boundary and security hardening

**Files:**
- Inspect and modify only confirmed production findings in `src/local_ai_hub/commands.py`, `src/local_ai_hub/http_server.py`, or related API modules.
- Test: nearest existing command/API security test; add a regression test for each confirmed finding.

**Interfaces:**
- Preserve command classification/approval policy and bounded subprocess execution.
- Preserve structured error responses and redaction rules.

- [ ] Verify the security scanner finding near `commands.py:496` is pattern data rather than executable `eval`/`exec`; if it is a false positive, add no code change and record it.
- [ ] Check production-only secret scans separately from test fixtures; remove or replace only real credentials, never illustrative fixtures required by tests.
- [ ] Verify dashboard/API inputs are bounded, authenticated where required, escaped at render boundaries, and do not leak raw secrets or full prompts into telemetry.
- [ ] Run focused security/API tests and the command broker tests.

### Task 5: Bounded performance and operational robustness

**Files:**
- Modify only confirmed hot paths in `src/local_ai_hub/async_jobs.py`, `src/local_ai_hub/scheduler.py`, `src/local_ai_hub/dashboard.py`, or state/query modules.
- Test: add benchmark-style bounded tests only where a current regression is demonstrated; otherwise use existing timeout/leak tests.

**Interfaces:**
- Keep all subprocess/network waits bounded and preserve cancellation semantics.
- Keep dashboard polling/event stream frequency and payload sizes bounded.

- [ ] Use complexity and existing timeout/leak tests to identify an actual high-cost path, not merely a high cyclomatic-complexity score in tests.
- [ ] Add a bounded test for the chosen path, then implement one localized optimization with unchanged output semantics.
- [ ] Verify no unbounded list/DOM growth, duplicate timer, SQLite lock, or retry loop is introduced.
- [ ] Run the focused performance/reliability tests and selftest.

### Task 6: Full verification and handoff

**Files:**
- Inspect: `git diff`, `docs/TESTING.md`, `tools/release_check.py`.
- Modify: only tests/docs needed to document confirmed fixes.

- [ ] Run `.venv\\Scripts\\python.exe -m compileall -q src tools tests`.
- [ ] Run `.venv\\Scripts\\python.exe -m pytest -q`.
- [ ] Run `python tools/selftest.py`, `python tools/check_dashboard.py`, and `python tools/doctor.py`.
- [ ] Run `python tools/release_check.py` and review the final clean/changed-file state.
- [ ] Perform a final diff/security review; report any remaining environmental skips or flaky tests explicitly.

## Self-review

- Scope is split into async, dashboard, security/API, performance, and release gates; each task owns its tests.
- No speculative local-model findings are treated as defects; the first semantic audit produced unsupported paths and is intentionally excluded.
- The prior targeted async failure is treated as a candidate until repeated evidence establishes a deterministic cause.
- No task authorizes commits, pushes, resets, or broad dependency changes.
