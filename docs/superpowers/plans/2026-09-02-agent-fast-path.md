# Agent Fast-Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give cloud agents trustworthy fast-path, cache, reliability, and quality/cost evidence without changing Qwen 9B performance behavior.

**Architecture:** Keep existing cache keys and local-model scheduler behavior intact. Extend metadata-only telemetry using current event columns and stage events, calculate cohort-specific summaries from persisted events, and expose only compact additions through existing status/task/report surfaces. Treat policy, duplicate-work, and cancellation outcomes as separate terminal categories rather than runtime failures or retries.

**Tech Stack:** Python 3.11, SQLite/WAL, existing `TelemetryStore`, HTTP/MCP servers, pytest.

---

### Task 1: Cohort-specific telemetry summary

**Files:**
- Create: `tests/test_telemetry_cohorts.py`
- Modify: `src/local_ai_hub/telemetry.py:215-256`
- Modify: `src/local_ai_hub/telemetry.py:568-658`

- [ ] **Step 1: Write failing cohort tests**

```python
def test_summary_keeps_agent_http_and_inference_percentiles_separate(tmp_path):
    store = TelemetryStore(tmp_path, enabled=True, flush_interval_seconds=0.01)
    try:
        store.record_http(action="/v1/repo/search", agent="codex", success=True, duration_ms=8)
        store.record(event_type="inference", action="delegate:review", success=True, duration_ms=8_000)
        store.flush(1)
        summary = store.summary(1)
    finally:
        store.close()

    assert summary["cohorts"]["agent_http"]["p95_duration_ms"] == 8
    assert summary["cohorts"]["inference"]["p95_duration_ms"] == 8_000
```

```python
def test_summary_labels_policy_block_separately_from_operational_failure(tmp_path):
    store = TelemetryStore(tmp_path, enabled=True, flush_interval_seconds=0.01)
    try:
        store.record_http(action="/v1/command", success=True, status_code=400, error_type="policy_block")
        store.record_http(action="/v1/repo/search", success=False, status_code=503, error_type="http_error")
        store.flush(1)
        summary = store.summary(1)
    finally:
        store.close()

    assert summary["cohorts"]["policy_rejection"]["events"] == 1
    assert summary["cohorts"]["agent_http"]["failures"] == 1
```

- [ ] **Step 2: Run tests; verify RED**

Run: `python -m pytest -q tests/test_telemetry_cohorts.py`

Expected: FAIL because `summary["cohorts"]` does not exist.

- [ ] **Step 3: Add metadata-only cohort classifier and aggregate helper**

In `TelemetryStore`, add private helpers that derive a cohort from existing
event fields, without changing the derived SQLite schema:

```python
@staticmethod
def _cohort(event_type: str, error_type: str) -> str:
    if event_type == "inference":
        return "inference"
    if event_type == "http" and error_type == "policy_block":
        return "policy_rejection"
    if event_type == "http":
        return "agent_http"
    return "internal"
```

Query `events` independently for each cohort. Return per-cohort `events`,
`failures`, `failure_rate`, `p50_duration_ms`, `p95_duration_ms`,
`p99_duration_ms`, `retry_count`, `fallback_count`, and `degraded_count`.
Keep legacy aggregate percentile fields but add `aggregate_duration_scope` with
value `"inference_and_http_diagnostic_only"`.

- [ ] **Step 4: Run focused tests; verify GREEN**

Run: `python -m pytest -q tests/test_telemetry_cohorts.py tests/test_surface_and_packaging.py::test_telemetry_summary_exposes_request_and_savings_totals`

Expected: PASS.

- [ ] **Step 5: Commit**

Repository is not Git-backed. Do not manufacture a commit; retain the tested
working-tree change for the next task.

### Task 2: Correct HTTP outcome and retry classification

**Files:**
- Create: `tests/test_http_telemetry_outcomes.py`
- Modify: `src/local_ai_hub/http_server.py:315-352`
- Modify: `src/local_ai_hub/http_server.py:378-392`
- Modify: `src/local_ai_hub/telemetry.py:215-274`

- [ ] **Step 1: Write failing handler telemetry tests**

```python
def test_policy_block_is_not_recorded_as_runtime_failure(monkeypatch):
    event = _send_and_capture(
        monkeypatch,
        path="/v1/command",
        status=400,
        data={"success": False, "policy_blocked": True, "terminal": True, "retryable": False},
    )
    assert event["success"] == 1
    assert event["error_type"] == "policy_block"
    assert event["retry_count"] == 0
```

```python
def test_duplicate_in_progress_is_not_recorded_as_a_retry_attempt(monkeypatch):
    event = _send_and_capture(
        monkeypatch,
        path="/v1/command",
        status=409,
        data={"success": False, "in_progress": True, "retryable": True},
    )
    assert event["error_type"] == "in_progress"
    assert event["retry_count"] == 0
```

- [ ] **Step 2: Run tests; verify RED**

Run: `python -m pytest -q tests/test_http_telemetry_outcomes.py`

Expected: FAIL because `in_progress` currently records generic `http_error`.

- [ ] **Step 3: Classify terminal client outcomes at HTTP boundary**

Before `record_http`, derive `outcome_error_type` in this precedence order:

```python
if policy_blocked:
    outcome_error_type = "policy_block"
elif isinstance(data, dict) and data.get("in_progress"):
    outcome_error_type = "in_progress"
elif isinstance(data, dict) and data.get("terminal") and status < 500:
    outcome_error_type = "terminal_client_result"
elif not success:
    outcome_error_type = "http_error"
else:
    outcome_error_type = ""
```

Keep `retry_count` reserved for an actual executed runtime retry. Do not call
`record_error` for policy, duplicate-work, or terminal-client categories.

- [ ] **Step 4: Run focused tests; verify GREEN**

Run: `python -m pytest -q tests/test_http_telemetry_outcomes.py tests/test_deeper_hardening.py::test_telemetry_recent_http_history_is_persistent`

Expected: PASS.

- [ ] **Step 5: Commit**

Repository is not Git-backed. Do not manufacture a commit.

### Task 3: Cache-decision evidence and duplicate-work guidance

**Files:**
- Create: `tests/test_cache_decision_telemetry.py`
- Modify: `src/local_ai_hub/services.py:250-481`
- Modify: `src/local_ai_hub/telemetry.py:568-658`
- Modify: `src/local_ai_hub/mcp_server.py:101-139`
- Modify: `mcp/local_ai_mcp.py:97-126`

- [ ] **Step 1: Write failing cache-decision tests**

```python
def test_generation_miss_records_metadata_only_reason(services, telemetry):
    result = services._generate(
        model="fast", prompt="Question: cache decision", system="", max_tokens=64,
        temperature=0, tenant="tenant-a", source="delegate:review",
        priority=1, internal=True,
    )
    assert result["cache_layer"] == "ollama"
    telemetry.flush(1)
    assert telemetry.report(1)["cache_decisions"]["new_exact_key"] == 1
```

```python
def test_exact_generation_cache_reuses_result_across_tenants(services):
    first = services._generate(
        model="fast", prompt="Question: shared exact key", system="", max_tokens=64,
        temperature=0, tenant="tenant-a", source="delegate:review", priority=1,
        internal=True,
    )
    second = services._generate(
        model="fast", prompt="Question: shared exact key", system="", max_tokens=64,
        temperature=0, tenant="tenant-b", source="delegate:review", priority=1,
        internal=True,
    )
    assert second["cache_layer"] == "exact"
```

- [ ] **Step 2: Run tests; verify RED**

Run: `python -m pytest -q tests/test_cache_decision_telemetry.py tests/test_generation_cache_keys.py`

Expected: FAIL because no `cache_decisions` report exists.

- [ ] **Step 3: Emit only safe cache-decision stage events**

After `generation_cache.get_or_compute`, record a stage event only for a
non-hit decision. Use existing `stage` and `error_type` columns; never record
prompt, system prompt, code, repository path, or hash.

```python
if cache_layer == "ollama":
    self.telemetry.record_stage(
        tenant=tenant,
        action=source,
        stage="cache_decision",
        success=True,
        error_type="new_exact_key",
    )
```

For semantic reuse attempts, distinguish `semantic_reused` and
`semantic_not_reused`; retain current scope and threshold unchanged. Extend
`TelemetryStore.report` with counts grouped by this stage/error-type pair.

Update both MCP tool descriptions to state that `in_progress` means reuse the
existing result via `wait`/`result`, never start a duplicate request.

- [ ] **Step 4: Run focused tests; verify GREEN**

Run: `python -m pytest -q tests/test_cache_decision_telemetry.py tests/test_generation_cache_keys.py tests/test_v1_5_reliability.py::test_singleflight_waiter_returns_retryable_in_progress_quickly`

Expected: PASS.

- [ ] **Step 5: Commit**

Repository is not Git-backed. Do not manufacture a commit.

### Task 4: Matched quality/cost evaluation records

**Files:**
- Create: `tests/test_evaluation_records.py`
- Modify: `src/local_ai_hub/telemetry.py:445-456`
- Modify: `src/local_ai_hub/telemetry.py:660-766`
- Modify: `src/local_ai_hub/services.py:557-581`
- Modify: `src/local_ai_hub/http_server.py:967-968`
- Modify: `src/local_ai_hub/mcp_server.py:101-139`
- Modify: `mcp/local_ai_mcp.py:97-126`

- [ ] **Step 1: Write failing evaluation tests**

```python
def test_unmatched_evaluation_is_not_claimed_as_quality_gain(tmp_path):
    store = TelemetryStore(tmp_path, enabled=True)
    try:
        store.record_snapshot("agent_evaluation", {
            "task_id": "case-1", "cohort": "hub_on", "quality_pass": True,
            "test_pass": True, "duration_ms": 8,
        })
        store.flush(1)
        report = store.report(1)
    finally:
        store.close()

    assert report["evaluation"]["verdict"] == "insufficient_evidence"
```

```python
def test_matched_evaluation_compares_hub_on_and_off(tmp_path):
    store = TelemetryStore(tmp_path, enabled=True)
    try:
        store.record_evaluation(task_id="case-2", cohort="hub_on", quality_pass=True, test_pass=True, duration_ms=8)
        store.record_evaluation(task_id="case-2", cohort="hub_off", quality_pass=True, test_pass=True, duration_ms=12)
        store.flush(1)
        report = store.report(1)
    finally:
        store.close()
    assert report["evaluation"]["matched_tasks"] == 1
```

- [ ] **Step 2: Run tests; verify RED**

Run: `python -m pytest -q tests/test_evaluation_records.py`

Expected: FAIL because `report["evaluation"]` does not exist.

- [ ] **Step 3: Add compact evaluation record/report flow**

Use the existing `snapshots` table and a bounded JSON payload to avoid a
telemetry migration. Add `TelemetryStore.record_evaluation` that validates:
`task_id` (opaque identifier, max 96 chars), `cohort` (`hub_on`/`hub_off`),
optional boolean `quality_pass`, optional boolean `test_pass`, and numeric
latency/token/cache metadata. Reject source text, prompts, paths, and arbitrary
objects.

Extend `benchmark` with an explicit `action="evaluation_report"` path that
returns a matched report only. Expose it through existing task endpoints; do
not add a public MCP tool. Report `insufficient_evidence` unless a task id has
one valid `hub_on` and one valid `hub_off` record.

- [ ] **Step 4: Run focused tests; verify GREEN**

Run: `python -m pytest -q tests/test_evaluation_records.py tests/test_surface_and_packaging.py::test_telemetry_summary_exposes_request_and_savings_totals`

Expected: PASS.

- [ ] **Step 5: Commit**

Repository is not Git-backed. Do not manufacture a commit.

### Task 5: Dashboard/status projection and full validation

**Files:**
- Modify: `src/local_ai_hub/telemetry.py:327-389`
- Modify: `src/local_ai_hub/dashboard.py:251-257`
- Modify: `src/local_ai_hub/app.py:326-345`
- Modify: `tests/test_telemetry_cohorts.py`
- Modify: `docs/DASHBOARD.md:5-9`

- [ ] **Step 1: Write failing projection test**

```python
def test_realtime_summary_exposes_agent_and_inference_cohorts(tmp_path):
    store = TelemetryStore(tmp_path, enabled=True, flush_interval_seconds=0.01)
    try:
        store.record_http(action="/v1/repo/search", success=True, duration_ms=5)
        store.record(event_type="inference", success=True, duration_ms=500)
        store.flush(1)
        live = store.realtime_summary()
    finally:
        store.close()

    assert set(live["cohorts"]) >= {"agent_http", "inference"}
```

- [ ] **Step 2: Run test; verify RED**

Run: `python -m pytest -q tests/test_telemetry_cohorts.py::test_realtime_summary_exposes_agent_and_inference_cohorts`

Expected: FAIL because realtime summary does not project cohorts.

- [ ] **Step 3: Project cohort metrics without changing legacy fields**

Add `cohorts` to realtime status. Change dashboard labels to show agent p50/p95/p99 as the main latency metric and local-inference p50/p95/p99 separately. Show policy rejections separately from operational failures. Label all token/currency values as estimates.

- [ ] **Step 4: Run full validation**

Run: `python -m compileall -q src mcp tools tests`

Expected: PASS with no output.

Run: `python -m pytest -q`

Expected: PASS.

Run: `python tools/selftest.py`

Expected: PASS.

- [ ] **Step 5: Review final diff**

Run: `git diff -- src/local_ai_hub/telemetry.py src/local_ai_hub/http_server.py src/local_ai_hub/services.py src/local_ai_hub/dashboard.py src/local_ai_hub/mcp_server.py mcp/local_ai_mcp.py tests docs/DASHBOARD.md`

Expected: unavailable because this directory is not a Git repository. Inspect
the explicit changed-file list with `git diff --no-index` only if a baseline is
provided; otherwise use targeted file review and test output.
