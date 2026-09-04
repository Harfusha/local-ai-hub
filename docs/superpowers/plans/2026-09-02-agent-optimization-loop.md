# Agent Optimization Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve cloud-agent p95/p99, cache reuse, and rollout evidence without model changes.

**Architecture:** Reuse existing telemetry, durable jobs, repo revision cache, artifact store, and command broker. Add process cohort reporting, safe endpoint delivery, cache warm/admission metadata, terminal command capability outcomes, resumable context artifacts, and report-only SLO/canary data.

**Tech Stack:** Python 3.11, SQLite/WAL, threaded HTTP server, pytest.

---

### Task 1: Deployment cohorts and SLO telemetry

**Files:** `src/local_ai_hub/telemetry.py`, `src/local_ai_hub/http_server.py`, `tests/test_telemetry_tail_latency.py`

- [x] RED: process cohort excludes earlier telemetry rows.
- [x] GREEN: expose `scope=process` summaries, per-agent SLO buckets, and cache effectiveness metrics.

### Task 2: Repository delivery and resumable context

**Files:** `src/local_ai_hub/http_server.py`, `src/local_ai_hub/async_jobs.py`, `src/local_ai_hub/services.py`, `tests/test_delivery_policy.py`

- [x] Verified: model delivery already uses durable jobs; response compaction already emits bounded artifacts. Repository reads remain synchronous to avoid routing them through a model lane.
- [x] Verified: root-fingerprint cache and artifact continuation preserve the sync contract without a new retry path.

### Task 3: Cache warm/admission and canonical query evidence

**Files:** `src/local_ai_hub/services.py`, `src/local_ai_hub/preprocess.py`, `tests/test_preprocessor_and_deterministic.py`

- [x] Verified: deterministic/code-index queries canonicalize terms and use root-revision keys; preprocessing warms hot capsules.
- [x] Verified: existing cache decisions and tier counters are telemetry-visible; no duplicate cache layer added.

### Task 4: Command capabilities and optional backend quarantine

**Files:** `src/local_ai_hub/commands.py`, `src/local_ai_hub/external_tools.py`, `tests/test_command_suppression.py`, `tests/test_external_tools.py`

- [x] Verified: command broker rejects missing safe executables before spawn; external backends use root-local circuit cooldowns.
- [x] Verified: optional failures degrade to built-in indexes instead of retries.

### Task 5: Evaluation canary and docs

**Files:** `src/local_ai_hub/telemetry.py`, `src/local_ai_hub/http_server.py`, `docs/MCP_AND_AGENTS.md`, `docs/OPERATIONS.md`, tests

- [x] Verified: `evaluation_record`/`evaluation_report` already carry paired opaque canary evidence and cannot alter routing.
- [x] GREEN: process cohort/SLO API and operator documentation added.

### Task 6: Regression gate

- [x] Run focused tests, compileall, full pytest, and selftest through Local AI Hub.
