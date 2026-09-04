# Cloud Agent Mechanical Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut non-model cloud-agent p95/p99, duplicate calls and terminal errors while preserving existing model policy.

**Architecture:** Add deterministic client preflight and endpoint cache outcome propagation; keep slow repository continuation in an artifact/mechanical path; use capability health and report-only SLO evaluation for safe fallback decisions.

**Tech Stack:** Python 3.11+, SQLite/WAL, threaded HTTP server, pytest.

---

### Task 1: Client terminal preflight

**Files:** `src/local_ai_hub/client.py`, `src/local_ai_hub/mcp_server.py`, `tests/test_client_preflight.py`

- [x] RED: invalid symbol and non-Git diff return terminal result without invoking transport.
- [x] GREEN: add canonical preflight helper and reuse it in `HubClient.request`.
- [x] Verify focused pytest.

### Task 2: Repository cache outcome contract

**Files:** `src/local_ai_hub/services.py`, `src/local_ai_hub/http_server.py`, `src/local_ai_hub/telemetry.py`, `tests/test_repo_cache_outcomes.py`

- [x] RED: repeated revision-equivalent repository call exposes `cache_hit` and endpoint telemetry cache layer.
- [x] GREEN: annotate `_repo_cached` results and HTTP telemetry without changing cache contents or model behavior.
- [x] Verify focused pytest.

### Task 3: Bounded context continuation

**Files:** `src/local_ai_hub/services.py`, `src/local_ai_hub/http_server.py`, `tests/test_context_delivery.py`

- [x] RED: `mode=fast` returns deterministic context plus full-continuation metadata, never calls a model job.
- [x] GREEN: add bounded mechanical fast context and retain full-context compatibility default.
- [x] Verify focused pytest.

### Task 4: Command and optional-backend health

**Files:** `src/local_ai_hub/commands.py`, `src/local_ai_hub/external_tools.py`, `src/local_ai_hub/app.py`, `tests/test_command_suppression.py`, `tests/test_external_tools.py`

- [x] Verified: command broker already rejects unavailable executables before spawn; external status already reports permanent CodeGraph quarantine and root circuits.
- [x] Verified: application capabilities expose backend status; built-in indexes remain fallback.

### Task 5: SLO evaluation and docs

**Files:** `src/local_ai_hub/telemetry.py`, `docs/MCP_AND_AGENTS.md`, `docs/OPERATIONS.md`, tests

- [x] Verified: evaluation is opaque, paired and report-only; it cannot mutate routing.
- [x] GREEN: endpoint cache/outcome and current-process SLO guidance documented.

### Task 6: Regression gate

- [x] Run `python -m compileall -q src mcp tools tests`, `python -m pytest -q`, and `python tools/selftest.py` through Local AI Hub.
