# Serena Timeouts, Soft Fallback to CodeIndex, and 1-Hour Project Session Pool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Increase Serena hard timeouts to 60s to prevent process kill cascades, add a 4s soft timeout with instant fallback to `CodeIndex`, and keep dedicated Serena instances alive for 1 hour (3600s TTL) for each active project.

**Architecture:** Update configuration defaults in `defaults.toml` and `config.py`. Enhance `MCPStdioClient` to distinguish between non-destructive soft query timeouts and hard process-killing timeouts (60s). Extend `ExternalCodeIntelligence.query_serena` to fall back to `CodeIndex` seamlessly when soft timeout is reached or project lock is contested. Update session lifecycle to retain active project sessions up to 3600s with capacity for 16 concurrent projects.

**Tech Stack:** Python 3.11+, `threading`, `subprocess`, `queue`, `pytest`.

---

### File Structure Map

- Modify:
  - `defaults.toml`: Update `query_timeout_seconds`, `startup_timeout_seconds`, add `soft_timeout_seconds`, update `session_idle_ttl_seconds` and `max_sessions_per_backend`.
  - `src/local_ai_hub/defaults.toml`: Matching updates to bundled defaults.
  - `src/local_ai_hub/config.py`: Add validation for `soft_timeout_seconds`.
  - `src/local_ai_hub/external_tools.py`:
    - `MCPStdioClient`: Add `soft_timeout` support to `call_tool` and `_request` without killing process.
    - `ExternalCodeIntelligence`: Connect `soft_timeout_seconds`, implement fallback to `CodeIndex` on soft timeout or lock contention, set 3600s session TTL and 16 max sessions.
  - `tests/test_external_tools.py`: Add tests for soft timeout fallback, hard timeout process kill, and 1-hour session retention.

---

### Task 1: Update Configuration & Defaults

**Files:**
- Modify: `defaults.toml:500-515`
- Modify: `src/local_ai_hub/defaults.toml:500-515`
- Modify: `src/local_ai_hub/config.py:218-223`
- Test: `tests/test_config.py`

- [x] **Step 1: Write test for new code_intelligence config options**

Add test in `tests/test_external_tools.py` verifying that `soft_timeout_seconds`, `query_timeout_seconds=60`, `startup_timeout_seconds=60`, and `session_idle_ttl_seconds=3600` are validated and accepted.

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_external_tools.py -k test_code_intelligence_timeouts`
Expected: FAIL (missing validation or default values).

- [x] **Step 3: Update `defaults.toml`, `src/local_ai_hub/defaults.toml`, and `config.py`**

In `[code_intelligence]`:
```toml
startup_timeout_seconds = 60
query_timeout_seconds = 60
soft_timeout_seconds = 4.0
session_idle_ttl_seconds = 3600
max_sessions_per_backend = 16
```
In `config.py`: add `soft_timeout_seconds` to `_number(intel, "soft_timeout_seconds", minimum=0.1, maximum=300)`.

- [x] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_external_tools.py -k test_code_intelligence_timeouts`
Expected: PASS.

- [x] **Step 5: Commit changes**

Git commit configuration updates.

---

### Task 2: Implement Non-Destructive Soft Timeout in `MCPStdioClient`

**Files:**
- Modify: `src/local_ai_hub/external_tools.py:175-240`
- Test: `tests/test_external_tools.py`

- [x] **Step 1: Write unit test for soft timeout without process kill**

Write test `test_mcp_stdio_soft_timeout_does_not_kill_process` in `tests/test_external_tools.py`:
Mock process that does not respond within soft timeout. Verify `call_tool(..., soft_timeout=0.1)` raises `TimeoutError` or returns soft timeout indicator, but `client._proc` is still alive (not killed).

- [x] **Step 2: Run test to verify failure**

Run: `python -m pytest tests/test_external_tools.py -k test_mcp_stdio_soft_timeout`
Expected: FAIL (currently `_request` unconditionally calls `_stop_process()`).

- [x] **Step 3: Implement soft timeout in `_request` and `call_tool`**

In `MCPStdioClient`:
1. Add `soft_timeout: float | None = None` parameter to `_request` and `call_tool`.
2. When `soft_timeout` is provided, calculate `soft_deadline = time.monotonic() + soft_timeout`.
3. If `time.monotonic() >= soft_deadline` before receiving matching response:
   - Raise `TimeoutError(f"MCP soft timeout: {method}")` (or custom `MCPSoftTimeoutError`).
   - Do NOT call `self._stop_process()`.
4. Only when `hard_deadline` (`call_timeout`, 60s) is exceeded without receiving response, call `self._stop_process()` and raise hard `TimeoutError`.

- [x] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_external_tools.py -k test_mcp_stdio_soft_timeout`
Expected: PASS.

- [x] **Step 5: Commit changes**

Git commit `MCPStdioClient` soft timeout.

---

### Task 3: Implement `CodeIndex` Fallback in `ExternalCodeIntelligence`

**Files:**
- Modify: `src/local_ai_hub/external_tools.py:350-400,968-1035`
- Test: `tests/test_external_tools.py`

- [x] **Step 1: Write test for Serena soft timeout fallback to `CodeIndex`**

In `tests/test_external_tools.py`, write `test_query_serena_soft_timeout_fallback_to_code_index`:
Initialize `ExternalCodeIntelligence` with a mock or slow Serena and a mock `CodeIndex`.
Call `query(root, "my_func", backend="serena", action="find_symbol")`.
Verify that on soft timeout, the result comes from `CodeIndex`, with `backend="code_index"`, `fallback_used=True`, and `degraded_reason="serena_soft_timeout"`.

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_external_tools.py -k test_query_serena_soft_timeout_fallback`
Expected: FAIL (no fallback implemented).

- [x] **Step 3: Implement fallback in `query_serena` / `query`**

1. Store `self.soft_timeout = float(self.cfg.get("soft_timeout_seconds", 4.0))`.
2. Accept optional `code_index` in `ExternalCodeIntelligence(..., code_index=None)`.
3. In `query_serena(root, action, query, ...)`:
   - Pass `soft_timeout` to `_backend_operation` (with lock wait max `min(soft_timeout, 1.5)` so it doesn't queue behind another slow query).
   - In `_query_serena_locked`, pass `soft_timeout=soft_timeout` to `client.call_tool(...)`.
   - On soft timeout or lock wait timeout:
     - If `self.code_index` is available:
       - For `find_symbol` / `search`: call `self.code_index.find_symbol(root, query)` / `search(root, query)`.
       - Return formatted results with `backend: "code_index"`, `fallback_used: True`, `degraded_reason: "serena_soft_timeout"`.
     - Else return soft timeout degraded response.

- [x] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_external_tools.py -k test_query_serena_soft_timeout_fallback`
Expected: PASS.

- [x] **Step 5: Commit changes**

Git commit `CodeIndex` fallback on soft timeout.

---

### Task 4: Configure 1-Hour Dedicated Session Pool per Project

**Files:**
- Modify: `src/local_ai_hub/external_tools.py:372-375,487-512`
- Test: `tests/test_external_tools.py`

- [x] **Step 1: Write test for 1-hour session retention and capacity**

In `tests/test_external_tools.py`, write `test_serena_session_retained_for_one_hour`:
Verify `session_idle_ttl` defaults to 3600.0s.
Simulate multiple projects; ensure sessions with last access < 3600s are NOT evicted when `len(sessions) <= 16`.

- [x] **Step 2: Run test to verify failure**

Run: `python -m pytest tests/test_external_tools.py -k test_serena_session_retained_for_one_hour`
Expected: FAIL.

- [x] **Step 3: Update `ExternalCodeIntelligence` session retention defaults**

Ensure:
- `self.session_idle_ttl = max(1.0, float(self.cfg.get("session_idle_ttl_seconds", 3600.0)))`
- `self.max_sessions = max(1, int(self.cfg.get("max_sessions_per_backend", 16)))`
- `_prune_sessions_locked` accurately checks `now - touched > self.session_idle_ttl` (3600s).

- [x] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_external_tools.py -k test_serena_session_retained_for_one_hour`
Expected: PASS.

- [x] **Step 5: Commit changes**

Git commit session retention updates.

---

### Task 5: End-to-End Verification & Regression Suite

**Files:**
- Test: `tests/test_external_tools.py`
- Test: `tests/test_reliability_core.py`

- [x] **Step 1: Run full external tools test suite**

Run: `python -m pytest tests/test_external_tools.py -v`
Expected: All tests PASS.

- [x] **Step 2: Run reliability core test suite**

Run: `python -m pytest tests/test_reliability_core.py -v`
Expected: All tests PASS.

- [x] **Step 3: Run repository compile check**

Run: `python -m compileall -q src`
Expected: Clean exit code 0.

- [x] **Step 4: Final commit and summary**

Commit all verified changes.
