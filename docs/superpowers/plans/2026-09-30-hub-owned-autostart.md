# Hub-Owned On-Demand Autostart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Keep every change in the approved `client.py` scope and T03 checkout.

**Goal:** Make one bounded Hub startup generation serve concurrent eligible clients and clean up only a failed child no live waiter can still use.

**Architecture:** Keep startup ownership in `HubClient`; use the existing state-directory OS guard as the synchronization boundary for generation and waiter metadata. Track each child by PID plus process creation identity, register waiters before health polling, and terminate/reap only after a failed generation has no live waiter. Preserve disabled/managed/listener checks, request deadlines, HTTP retry rules, and all eight MCP tools.

**Tech Stack:** Python 3.11+, `HubClient`, state-directory lock files, `process_utils.py` hidden spawn and process-tree termination helpers, pytest.

---

## File map

- Modify `src/local_ai_hub/client.py`: generation ownership, waiter registration/reclamation, bounded failure cleanup. Keep edits inside the user-approved narrow `client.py` scope.
- Create `tests/test_hub_startup_coordination.py`: deterministic lifecycle/concurrency regressions using fake child processes, fake health checks, and temporary state directories.
- Preserve `src/local_ai_hub/process_utils.py`: reuse its Windows hidden-process and process-tree helpers; do not add new process primitives there without revising this plan.
- Preserve public MCP/HTTP contracts: no tool, endpoint, or schema changes.

## Task 1: Lock down existing startup boundaries

**Files:** `tests/test_hub_startup_coordination.py` (create)

- [ ] Add tests proving `auto_start=False`, disabled marker, managed marker, live supervisor, and existing listener never spawn a direct child.
- [ ] Add tests proving spawn `OSError` returns unavailable and clears only this generation's lock metadata.
- [ ] Add tests proving startup wait is capped by remaining request budget and `bounded_startup_wait` limits remain finite.
- [ ] Run the focused file through the assigned shared test slot. Expected: new tests expose only missing assertions; existing behavior tests pass.

## Task 2: Register callers to one startup generation

**Files:** `src/local_ai_hub/client.py`, `tests/test_hub_startup_coordination.py`

- [ ] Define private helpers for generation metadata and waiter records under `server.state_dir`; store only generation ID, owner/waiter PID, creation identity, and state (`starting`, `ready`, `failed`, `stopping`).
- [ ] Guard every read-modify-write transition with the existing cross-process `hub.start.guard`; write records atomically through a temporary file plus replace while holding the guard.
- [ ] Register a caller before it relies on a generation; release its record from `finally` on success, timeout, exceptions, and cancellation.
- [ ] Reclaim a waiter record only when PID and process creation identity prove it stale. Unknown identity remains live until bounded stale policy proves otherwise; never infer liveness from directory counts alone.
- [ ] Add a barrier-based concurrency test: two clients sharing one state directory start together, exactly one `Popen` occurs, both callers observe the same ready generation.
- [ ] Run only the focused concurrency selector through the assigned test slot. Expected: one child, two successful callers, no stale waiter record.

## Task 3: Make readiness and failure transitions atomic

**Files:** `src/local_ai_hub/client.py`, `tests/test_hub_startup_coordination.py`

- [ ] Mark the generation `ready` after bounded health succeeds; retain the child as the Hub service after the initiating client exits.
- [ ] On spawn failure, mark the generation `failed`, remove its startup ownership record, and return the existing normalized unavailable result.
- [ ] On readiness timeout, mark the generation `failed` under the guard before deciding cleanup. A client timeout must not kill a ready generation or a managed Hub.
- [ ] Test readiness success leaves the daemon running after caller return; test spawn failure leaves no lock/waiter residue.
- [ ] Run the focused transition selectors through the assigned test slot. Expected: all transitions terminate within configured startup bounds.

## Task 4: Clean up failed children after the last live waiter

**Files:** `src/local_ai_hub/client.py`, `tests/test_hub_startup_coordination.py`

- [ ] When a generation fails, defer child cleanup while any registered waiter is live; the final waiter claims cleanup with one guarded `failed -> stopping` transition.
- [ ] Before termination, verify the recorded child PID and process creation identity still match. If a listener or replacement generation owns the port, do not terminate it.
- [ ] Terminate with `process_utils.terminate_tree`; wait and reap with fixed bounds, then force-kill only the matching failed child if needed. Retain recoverable metadata when exit cannot be confirmed.
- [ ] Test no-waiter timeout terminates and reaps once; test one caller timing out does not kill a child still needed by another live waiter; test the final failed waiter performs cleanup exactly once.
- [ ] Test a stale PID reused by a different process never triggers termination of that process.
- [ ] Run the focused cleanup selectors through the assigned test slot. Expected: no orphan child, no duplicate cleanup, no healthy/managed Hub termination.

## Task 5: Verify platform launch and public compatibility

**Files:** `tests/test_hub_startup_coordination.py`, `tests/test_client_transport.py`, `tests/test_surface_inventory.py` (only if existing inventory assertions need coverage)

- [ ] Assert Windows launch still uses `hidden_run_kwargs(detached=True)` and non-Windows launch remains detached with a new session.
- [ ] Assert the original request retries only after loopback connection refusal and within its original remaining deadline; preserve current HTTP errors and public response shape.
- [ ] Assert the eight MCP tool names and HTTP dispatch surface remain unchanged.
- [ ] Run focused client/startup and surface-inventory tests through `local_ai_command` after the shared slot is assigned. Expected: all pass; no endpoint/schema diff.

## Task 6: Review and acceptance

- [ ] Run `git diff --check` and targeted AST/compile checks through the approved command path.
- [ ] Run the complete repository validation only when T20 assigns this checkout the shared slot; never overlap another task's test run.
- [ ] Request Bugbot review of the `client.py` diff and startup tests; fix only actionable findings inside approved scope, then request one follow-up review.
- [ ] Confirm changed paths are limited to `client.py` and the startup tests, plus no prompt/schema changes.
- [ ] Report exact HEAD, changed paths, test command/receipt, Bugbot findings, and remaining runtime limitations. Do not claim Windows process-tree behavior from mocked tests alone.

## Acceptance checklist

- One startup generation starts at most one Hub for one state directory.
- Every caller waits only within its original bounded request deadline.
- Failed startup cleans its child only after no live waiter can rely on it.
- Healthy, managed, disabled, or replacement Hub processes are never killed by timeout cleanup.
- Stale owner/waiter metadata is reclaimed only with PID plus process-identity checks.
- Windows child launch stays hidden; process-tree termination and reaping stay bounded.
- Eight MCP tools and HTTP dispatch contract remain unchanged.
