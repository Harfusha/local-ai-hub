# Cloud-agent reliability implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove avoidable cloud-agent overhead/errors while preserving quality and privacy.

**Architecture:** Reuse one loopback HTTP/1.1 connection per client thread and coalesce identical active client requests. Classify known protocol/client limitations as terminal or in-progress, permanently degrade a proven-broken optional backend, and expose a conservative A/B recommendation.

**Tech Stack:** Python 3.11+, stdlib `http.client`, existing recovery journal, telemetry SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-09-02-cloud-agent-reliability-design.md`

## Global constraints

- Default compatibility behavior remains unchanged; Qwen 9B is untouched.
- Tests precede production code and every network/process wait remains bounded.
- No prompt/source/output persistence or additional MCP tools.

### Task 1: Client transport and active-request deduplication

**Files:** `src/local_ai_hub/client.py`, `tests/test_client_transport.py`

- [x] Write failing tests: sequential calls reuse a connection; simultaneous identical calls execute once and waiter result is marked coalesced.
- [x] Add per-thread loopback connection lifecycle and bounded singleflight.
- [x] Run focused tests.

### Task 2: Expected outcome classification

**Files:** `src/local_ai_hub/http_server.py`, `src/local_ai_hub/repo_tools.py`, `src/local_ai_hub/services.py`, tests.

- [x] Write failing tests for recovery `in_progress` and non-Git terminal diff/impact outcomes.
- [x] Add metadata-only classification before raw Git invocation.
- [x] Run focused tests.

### Task 3: Optional backend and A/B gate

**Files:** `src/local_ai_hub/external_tools.py`, `src/local_ai_hub/telemetry.py`, `tests/test_external_tools.py`, `tests/test_evaluation_records.py`

- [x] Write failing tests for permanent CodeGraph package failure and conservative promotion gate.
- [x] Degrade only irreversible install errors; add report-only gate requiring ten matched quality/test observations.
- [x] Run focused tests.

### Task 4: Agent contract and verification

**Files:** `docs/MCP_AND_AGENTS.md`, `docs/OPERATIONS.md`

- [x] Document use of hot-query warming, `batch_delegate`, client coalescing, terminal/in-progress contract and A/B gate.
- [x] Run compileall, full pytest, self-test, restart/health/status, review changed paths, store memo and release lease.
