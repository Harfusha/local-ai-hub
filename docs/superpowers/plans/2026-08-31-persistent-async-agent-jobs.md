# Persistent Async Agent Jobs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let MCP agents submit durable local-model jobs, continue foreground work, and later wait for, fetch, or cancel their results.

**Architecture:** Add one persistent async-job manager above `AffinityScheduler`; it owns SQLite state, deduplication, durable leases, artifact references, and bounded cleanup. It submits executable work to the existing scheduler as low-priority background jobs, so foreground requests always win. Extend the existing `local_ai_task` surface and HTTP task handler with submit/status/wait/result/cancel actions; do not add an MCP tool or worker process.

**Tech Stack:** Python 3.11, SQLite/WAL, existing `AffinityScheduler`, `ArtifactStore`, `RecoveryJournal`, HTTP server, MCP server, pytest.

---

### Task 1: Durable job state and privacy boundary

**Files:**
- Create: `src/local_ai_hub/async_jobs.py`
- Modify: `config.toml`
- Modify: `defaults.toml`
- Test: `tests/test_async_jobs.py`

- [ ] **Step 1: Write failing persistence and deduplication tests**

```python
def test_submit_coalesces_same_tenant_and_canonical_request(tmp_path):
    jobs = AsyncJobManager(_config(tmp_path), _scheduler(), _artifacts())
    first = jobs.submit("tenant-a", _request("same"))
    second = jobs.submit("tenant-a", _request("same"))
    assert first["job_id"] == second["job_id"]
    assert second["coalesced"] is True


def test_submit_does_not_coalesce_across_tenants(tmp_path):
    jobs = AsyncJobManager(_config(tmp_path), _scheduler(), _artifacts())
    assert jobs.submit("tenant-a", _request("same"))["job_id"] != jobs.submit("tenant-b", _request("same"))["job_id"]
```

- [ ] **Step 2: Run the new tests before implementation**

Run: `python -m pytest -q tests/test_async_jobs.py`

Expected: FAIL because `local_ai_hub.async_jobs` does not exist.

- [ ] **Step 3: Implement `AsyncJobManager` and its SQLite schema**

```python
class AsyncJobManager:
    def submit(self, tenant: str, request: dict[str, Any]) -> dict[str, Any]: ...
    def status(self, tenant: str, job_id: str) -> dict[str, Any]: ...
    def wait(self, tenant: str, job_id: str, timeout_seconds: float) -> dict[str, Any]: ...
    def result(self, tenant: str, job_id: str) -> dict[str, Any]: ...
    def cancel(self, tenant: str, job_id: str) -> dict[str, Any]: ...
    def recover(self) -> int: ...
```

Create an `async_jobs` table with `job_id`, `tenant`, `request_hash`, `state`,
`payload_artifact_id`, `result_artifact_id`, `lease_until`, `attempts`,
`cancel_requested`, `created_at`, `updated_at`, and `expires_at`. Add a unique
index on `(tenant, request_hash)` only for active states. Store request payloads
and verbose outputs in tenant-scoped artifacts; persist only artifact ids and
hashes in the job table. State values are `queued`, `running`, `done`,
`failed`, `cancelled`, and `expired`.

- [ ] **Step 4: Add bounded configuration**

```toml
[async_jobs]
enabled = true
max_pending = 64
wait_max_seconds = 90
lease_seconds = 900
result_ttl_seconds = 259200
max_attempts = 2
cleanup_interval_seconds = 60
```

- [ ] **Step 5: Run persistence tests**

Run: `python -m pytest -q tests/test_async_jobs.py`

Expected: PASS for tenant isolation, active-job coalescing, and durable state.

### Task 2: Scheduler execution, recovery, and cancellation

**Files:**
- Modify: `src/local_ai_hub/async_jobs.py`
- Modify: `src/local_ai_hub/app.py`
- Modify: `src/local_ai_hub/scheduler.py`
- Test: `tests/test_async_jobs.py`

- [ ] **Step 1: Write failing scheduling tests**

```python
def test_async_job_uses_background_priority_and_foreground_can_run_first(tmp_path):
    scheduler = _RecordingScheduler()
    jobs = AsyncJobManager(_config(tmp_path), scheduler, _artifacts())
    jobs.submit("tenant", _request("slow"))
    jobs.dispatch_ready()
    assert scheduler.calls[0]["background"] is True
    assert scheduler.calls[0]["priority"] <= 1


def test_recovery_requeues_expired_running_lease_once(tmp_path):
    jobs = _manager_with_expired_running_job(tmp_path)
    assert jobs.recover() == 1
    assert jobs.status("tenant", "job-1")["state"] == "queued"
```

- [ ] **Step 2: Run scheduling tests before implementation**

Run: `python -m pytest -q tests/test_async_jobs.py -k "background or recovery"`

Expected: FAIL because dispatch and lease recovery are not implemented.

- [ ] **Step 3: Dispatch through the existing scheduler**

Submit every durable job through:

```python
self.scheduler.submit(
    model=model,
    tenant=tenant,
    source="async-job",
    execute=run_payload,
    priority=1,
    wait_timeout=0.05,
    background=True,
)
```

Do not wait on this scheduler call in the public submit path. The manager owns
the durable state transition and completion callback. Before executing, claim a
lease transactionally; after execution, store the compact result and artifact
reference, then mark the job terminal. Check `cancel_requested` before model
work and before publishing a result.

- [ ] **Step 4: Wire lifecycle in `LocalAIApp`**

Construct `AsyncJobManager` after `LocalAIServices` and `ArtifactStore` exist.
Call `recover()` once during startup. From the existing watchdog, invoke bounded
`dispatch_ready()` and cleanup at the configured interval. Include compact async
queue counts in full runtime status. On shutdown, stop dispatching but leave
queued rows durable.

- [ ] **Step 5: Run scheduling tests**

Run: `python -m pytest -q tests/test_async_jobs.py -k "background or recovery or cancel"`

Expected: PASS. Foreground work remains scheduler-owned and async work does not
create a process or terminal window.

### Task 3: MCP and HTTP task actions

**Files:**
- Modify: `src/local_ai_hub/mcp_server.py`
- Modify: `src/local_ai_hub/http_server.py`
- Modify: `src/local_ai_hub/app.py`
- Test: `tests/test_async_jobs.py`

- [ ] **Step 1: Write API contract tests**

```python
def test_task_submit_returns_immediately_with_job_id(client):
    response = client.post("/v1/task", json={"action": "submit", "task": "classify this"})
    assert response.status_code == 200
    assert response.json()["state"] in {"queued", "running"}
    assert response.json()["job_id"]


def test_task_wait_is_bounded_to_ninety_seconds(client):
    response = client.post("/v1/task", json={"action": "wait", "job_id": "job-1", "timeout_seconds": 999})
    assert response.json()["wait_timeout_seconds"] == 90
```

- [ ] **Step 2: Run API tests before implementation**

Run: `python -m pytest -q tests/test_async_jobs.py -k "task_submit or task_wait"`

Expected: FAIL because `local_ai_task` does not expose async actions.

- [ ] **Step 3: Extend `local_ai_task` and `/v1/task`**

Accept `submit`, `status`, `wait`, `result`, and `cancel`. Validate that submit
contains only supported existing task fields. Require `job_id` for all other
actions. Clamp `wait.timeout_seconds` to `1..90`. Return `terminal=true` and
`retryable=false` for unknown, cross-tenant, expired, or cancelled jobs. Return
an artifact id rather than inline verbose output.

- [ ] **Step 4: Preserve existing synchronous actions**

Route all existing `local_ai_task` actions unchanged. Async submit must call the
same internal action executor that synchronous task handling uses, preserving
model routing, generation cache, semantic cache, and telemetry behavior.

- [ ] **Step 5: Run API tests**

Run: `python -m pytest -q tests/test_async_jobs.py -k "task_submit or task_wait or cancel"`

Expected: PASS with no public MCP surface expansion.

### Task 4: Status, cleanup, and regression validation

**Files:**
- Modify: `src/local_ai_hub/async_jobs.py`
- Modify: `src/local_ai_hub/app.py`
- Modify: `src/local_ai_hub/dashboard.py`
- Test: `tests/test_async_jobs.py`
- Test: `tests/test_runtime_hardening.py`

- [ ] **Step 1: Add terminal-state and cleanup tests**

```python
def test_cancelled_job_never_returns_successful_result(tmp_path):
    jobs = _done_then_cancelled_manager(tmp_path)
    result = jobs.result("tenant", "job-1")
    assert result["success"] is False
    assert result["terminal"] is True


def test_expired_result_is_removed_by_cleanup(tmp_path):
    jobs = _manager_with_expired_result(tmp_path)
    assert jobs.cleanup() == 1
    assert jobs.status("tenant", "job-1")["state"] == "expired"
```

- [ ] **Step 2: Implement compact observability**

Expose counts only: queued, running, done, failed, cancelled, expired,
coalesced, recovered, and cleanup count. Do not include prompts, source text,
output text, artifact contents, secrets, or full roots in telemetry or status.

- [ ] **Step 3: Run targeted async tests**

Run: `python -m pytest -q tests/test_async_jobs.py tests/test_runtime_hardening.py`

Expected: PASS.

- [ ] **Step 4: Run repository validation**

Run: `python -m compileall -q src mcp tools tests`

Expected: exit code `0`.

Run: `python -m pytest -q`

Expected: all tests pass; the known POSIX-only permission test may skip on Windows.

Run: `python tools/selftest.py`

Expected: config, health, and public capability checks succeed.

