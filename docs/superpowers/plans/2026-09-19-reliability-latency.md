# Reliability and Latency Hardening Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove avoidable tail latency and repeated failures observed in the 30-day runtime telemetry while preserving intentional safety limits.

**Architecture:** Keep deterministic repository and command paths unchanged. Add a cheap backend-availability gate before model fallback attempts, make startup prewarm stop when no backend is usable, and expose large diff review as durable async work with a larger but bounded chunk budget.

**Tech Stack:** Python 3.11+, `unittest`/`pytest`, `ThreadingHTTPServer`, existing `AsyncJobManager`, Ollama/llama.cpp runtime adapters, SQLite telemetry.

---

### Task 1: Fail fast when all local model backends are offline

**Files:**
- Modify: `src/local_ai_hub/services.py` in `LocalAIServices._generate`
- Test: `tests/test_local_model_availability.py`

- [ ] **Step 1: Write the failing test**

Create a runtime fake whose `is_online()` returns `False`, invoke `_generate` with a minimal `LocalAIServices` fixture, and assert no scheduler submission occurs and the result is `success=False`, `retryable=True`, `error_code="local_backend_unavailable"`.

- [ ] **Step 2: Run the focused test and confirm failure**

Run: `python -m pytest -q tests/test_local_model_availability.py`
Expected: the new test fails because `_generate` currently enters model fallback/scheduler work.

- [ ] **Step 3: Add one availability gate after cache lookup**

In `compute_inner`, after semantic-cache reuse is checked and before constructing model attempts, call an optional `runtime.is_online()` method. When it returns false, return a bounded structured result with `success=False`, `unsupported=True`, `degraded=True`, `terminal=False`, `retryable=True`, `error_code="local_backend_unavailable"`, and no model fallback loop. If a test/runtime adapter has no callable `is_online`, preserve the existing path.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest -q tests/test_local_model_availability.py tests/test_model_routing.py tests/test_conversations.py`
Expected: all pass; offline path makes zero scheduler submissions.

### Task 2: Stop prewarm immediately when no backend is available

**Files:**
- Modify: `src/local_ai_hub/app.py` in `_start_background_threads`
- Test: `tests/test_prewarm_reliability.py`

- [ ] **Step 1: Write the failing test**

Construct the prewarm closure with a runtime fake returning `False` from `is_online()`, start the app background setup, wait for the thread, and assert `scheduler.prewarm` was never called and telemetry contains `prewarm_skipped_backend_unavailable`.

- [ ] **Step 2: Run focused test and confirm failure**

Run: `python -m pytest -q tests/test_prewarm_reliability.py`
Expected: failure because current code retries up to the default 120 attempts.

- [ ] **Step 3: Add the guarded early exit**

After the configured delay and before the retry loop, check the optional runtime availability method. If unavailable, log one warning, record `prewarm_skipped_backend_unavailable`, and return. Keep configured retry behavior for a backend that is online but temporarily busy.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest -q tests/test_prewarm_reliability.py tests/test_runtime_hardening.py`
Expected: all pass and no 120-attempt retry loop occurs for a disabled backend.

### Task 3: Make large review diffs durable and bounded

**Files:**
- Modify: `src/local_ai_hub/async_jobs.py`, `src/local_ai_hub/app.py`, `src/local_ai_hub/http_server.py`, `src/local_ai_hub/services.py`, `src/local_ai_hub/mcp_server.py`
- Modify: `src/local_ai_hub/defaults.toml`
- Test: `tests/test_review_diff_chunking.py`, `tests/test_async_jobs.py`, `tests/test_http_delivery.py`

- [ ] **Step 1: Add async action coverage**

Register `review_diff` in `AsyncJobManager.ACTIONS`, dispatch it from `LocalAIApp._execute_async_task`, and map `/api/review/diff` in `_async_delivery`. Preserve explicit `delivery=sync` behavior for callers that request it.

- [ ] **Step 2: Add bounded async chunk policy**

Keep the synchronous safety limit at 8 chunks. For an async review job, allow a configured limit of 32 chunks via `review.max_async_chunks`; reject larger diffs with a structured terminal error. Do not change per-chunk token budgets or unsplittable-fragment rejection.

- [ ] **Step 3: Route MCP review diff through automatic delivery**

Forward `delivery="auto"` and the existing latency budget from the MCP review-diff call so observed tail latency can select the durable job path. Do not change the user-owned unrelated MCP edits.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest -q tests/test_review_diff_chunking.py tests/test_async_jobs.py tests/test_http_delivery.py`
Expected: oversized async reviews complete through a durable job; synchronous oversized reviews retain the explicit bounded error.

### Task 4: Verify whole repository and runtime contract

**Files:**
- No source changes expected.

- [ ] **Step 1: Run syntax and targeted regression checks**

Run: `python -m compileall -q src mcp tools tests` and the focused suites from Tasks 1–3.

- [ ] **Step 2: Run repository validation**

Run: `python tools/release_check.py`, `python -m pytest -q`, and `python tools/selftest.py` through the command broker.

- [ ] **Step 3: Review diff and final status**

Run: `git diff --check`, `git status --short --branch`, and an indexed diff review. Report any remaining known runtime-only failures separately from code failures.
