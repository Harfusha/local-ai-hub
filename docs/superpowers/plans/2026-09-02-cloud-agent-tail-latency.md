# Cloud-Agent Tail-Latency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove avoidable duplicate failures and invalid backend work while producing safe data for cache and A/B optimization.

**Architecture:** RecoveryJournal gains bounded duplicate waiting. Handler rejects malformed code requests and records optional request-attached evaluation data. ExternalToolManager isolates transient circuits per root; existing revision cache and foreground scheduler remain source of truth.

**Tech Stack:** Python 3.11, sqlite3, threaded HTTP server, pytest.

---

### Task 1: Recovery duplicate wait

**Files:**
- Modify: `src/local_ai_hub/resilience.py`
- Modify: `src/local_ai_hub/http_server.py`
- Test: `tests/test_v1_5_reliability.py`

- [x] Add failing test: a second request waits for journal completion and receives stored response.
- [x] Run focused test; observe missing `wait_for` failure.
- [x] Add condition-notified `RecoveryJournal.wait_for` with bounded polling fallback.
- [x] Replay completed prior response before returning `in_progress`.
- [x] Run focused recovery tests.

### Task 2: Terminal input validation

**Files:**
- Modify: `src/local_ai_hub/http_server.py`
- Test: `tests/test_http_phase_telemetry.py`

- [x] Add failing tests for blank symbol, blank code graph target, and blank file path.
- [x] Run focused tests; observe validation does not reject input.
- [x] Validate required root/query/symbol/path fields before dispatch.
- [x] Return bounded terminal 400 results without external calls.
- [x] Run focused validation tests.

### Task 3: Per-root external circuits

**Files:**
- Modify: `src/local_ai_hub/external_tools.py`
- Test: `tests/test_external_tools.py`

- [x] Add failing test: a Serena failure for root A does not cooldown root B.
- [x] Run focused test; observe global cooldown.
- [x] Store transient failure/cooldown state by backend and resolved root.
- [x] Preserve process-wide broken-CodeGraph fallback.
- [x] Run focused external-tool tests.

### Task 4: Request-attached A/B evidence

**Files:**
- Modify: `src/local_ai_hub/http_server.py`
- Test: `tests/test_evaluation_records.py`
- Modify: `docs/MCP_AND_AGENTS.md`

- [x] Add failing test: ordinary successful request records supplied hub-on task metadata with measured duration.
- [x] Run focused test; observe no evaluation record.
- [x] Validate optional opaque evaluation metadata and record it when response completes.
- [x] Document paired hub-on/hub-off quality/test reporting; no automatic promotion.
- [x] Run focused evaluation tests.

### Task 5: Verify existing fast paths and regression gate

**Files:**
- Modify: `docs/OPERATIONS.md`
- Test: `tests/test_client_transport.py`

- [x] Assert pooled transport and local singleflight remain active.
- [x] Document revision-keyed artifact cache, semantic scope safeguards, and foreground scheduling as existing controls.
- [x] Run targeted cache/client tests.
- [x] Run `python -m compileall -q src mcp tools tests`, `python -m pytest -q`, and `python tools/selftest.py` through Local AI Hub.
