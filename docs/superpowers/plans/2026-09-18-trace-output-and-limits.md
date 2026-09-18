# Trace Output and Limits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make local model traces complete and readable while giving model operations enough token/time headroom to finish.

**Architecture:** Keep final response and structured thinking as separate fields/events from Ollama through the debug observer into the dashboard. Capture bounded API request/result projections at the HTTP boundary, and centralize larger but still bounded defaults in configuration.

**Tech Stack:** Python 3.11, Ollama NDJSON, SQLite debug traces, embedded dashboard JavaScript, pytest and Node renderer tests.

---

### Task 1: Capture final response and thinking separately

**Files:**
- Modify: `src/local_ai_hub/ollama.py`
- Modify: `src/local_ai_hub/debug_traces.py`
- Modify: `src/local_ai_hub/services.py`
- Test: `tests/test_repetition_watchdog_streaming.py` and a focused new regression test

- [ ] Add failing tests for structured `thinking` chunks, non-empty final response chunks, and ignored empty chunks.
- [ ] Run the focused tests and confirm failure because thinking is not collected and empty callbacks are emitted.
- [ ] Implement separate thinking accumulation/callbacks and an explicit empty-final-response status.
- [ ] Run the focused tests and the relevant existing streaming tests.

### Task 2: Capture repo/review trace payloads

**Files:**
- Modify: `src/local_ai_hub/http_server.py`
- Modify: `src/local_ai_hub/debug_traces.py`
- Test: `tests/test_debug_trace_request_summary.py` and dashboard trace tests

- [ ] Add failing tests proving repo/review traces retain bounded request/context/result projections.
- [ ] Implement one bounded trace projection helper at the API boundary.
- [ ] Verify missing fields remain “not captured” and are not confused with redaction.

### Task 3: Fix redaction and expandable dashboard output

**Files:**
- Modify: `src/local_ai_hub/dashboard.py`
- Test: `tests/test_dashboard_custom_modals.py`

- [ ] Add failing tests for visible final response, expandable thinking, and visible accounting metric keys.
- [ ] Narrow sensitive-key matching and add the output/thinking disclosure UI.
- [ ] Run the Node-backed dashboard tests.

### Task 4: Raise safe defaults and remove premature exhaustion

**Files:**
- Modify: `defaults.toml`
- Modify: `src/local_ai_hub/defaults.toml`
- Modify: `src/local_ai_hub/services.py`
- Modify: `src/local_ai_hub/ollama.py`
- Test: `tests/test_model_policy.py`, `tests/test_reliability_integration.py` and focused service tests

- [ ] Add failing tests for the new defaults and full request deadline behavior.
- [ ] Increase output/context/request/scheduler headroom within validation maxima; keep retries bounded and do not reset the deadline per attempt.
- [ ] Run focused reliability tests.

### Task 5: Full verification and review

- [ ] Run `python -m pytest -q` through `local_ai_command`.
- [ ] Run `python tools/release_check.py` through `local_ai_command`.
- [ ] Run `python -m compileall -q src mcp tools tests` through `local_ai_command`.
- [ ] Run `python tools/selftest.py` through `local_ai_command`.
- [ ] Review diff and run indexed security review.
