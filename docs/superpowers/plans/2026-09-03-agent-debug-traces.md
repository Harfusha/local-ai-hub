# Agent and API Debug Traces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add bounded, authenticated dashboard history and realtime detail for async workers, scheduler jobs, active API requests, and recent API requests.

**Architecture:** A shared `DebugTraceStore` stores full debug content in a separate SQLite/WAL database under `server.state_dir`; normal telemetry remains metadata-only. Existing request, async-job, scheduler, service, tool-agent, and Ollama flows emit ordered trace events. Dashboard polls detail incrementally once per second and cleanup deletes old terminal traces in small batches while protecting live work.

**Tech Stack:** Python 3.11, SQLite/WAL, `urllib` NDJSON streaming, existing HTTP server/dashboard, pytest.

---

## File map

- Create `src/local_ai_hub/debug_traces.py`: trace session/event schema, bounded writes/reads, filters, pagination, cleanup, size accounting.
- Create `tests/test_debug_traces.py`: store, limits, ordering, linking, and cleanup tests.
- Create `tests/test_ollama_tracing.py`: NDJSON aggregation and output callback tests.
- Create `tests/test_debug_dashboard.py`: dashboard trace route/rendering assertions.
- Modify `src/local_ai_hub/trace_context.py`: carry an optional trace observer through scheduler worker contexts without changing existing request identity behavior.
- Modify `src/local_ai_hub/ollama.py`: add callback-based NDJSON request path that aggregates the same final response.
- Modify `src/local_ai_hub/tiered_ollama.py`: route traced stream requests through selected fast/smart runtime.
- Modify `src/local_ai_hub/services.py` and `src/local_ai_hub/tool_agent.py`: emit effective prompts, tool events, and output deltas only when a trace observer exists.
- Modify `src/local_ai_hub/async_jobs.py`: create/link async traces, record lifecycle/retry/cancel events, expose history/detail data through the store.
- Modify `src/local_ai_hub/app.py`: construct the store, pass it to services/jobs, run bounded cleanup from the watchdog, expose trace stats.
- Modify `src/local_ai_hub/http_server.py`: capture request bodies/results/stages, attach API-to-job links, add authenticated dashboard GET endpoints.
- Modify `src/local_ai_hub/dashboard.py`: trace-aware rows, history controls, live detail panel, incremental polling, safe rendering.
- Modify `defaults.toml` and `src/local_ai_hub/defaults.toml`: trace enablement, TTL, byte/count/event limits, cleanup batch limits.
- Modify `docs/DASHBOARD.md` and `docs/HTTP_API.md`: explain trace detail, retention, and endpoints.
- Extend `tests/test_async_jobs.py`, `tests/test_http_phase_telemetry.py`, `tests/test_http_telemetry_outcomes.py`, `tests/test_runtime_hardening.py`, and add focused dashboard/API assertions where existing fixtures make that cheaper.

## Task 1: Trace store and bounded retention

**Files:** create `src/local_ai_hub/debug_traces.py`, `tests/test_debug_traces.py`; modify both defaults files.

- [ ] **Step 1: Write failing store tests.** Define `_config(tmp_path)` with a small `max_bytes`, `max_events_per_session`, `max_sessions`, and `cleanup_batch_size`. Assert this wished-for API:

```python
store = DebugTraceStore(_config(tmp_path))
trace_id = store.start(kind="async_job", tenant="t", agent="a", action="reason")
store.event(trace_id, "model_request", {"prompt": "full prompt"})
store.event(trace_id, "output_delta", {"text": "part"})
store.finish(trace_id, state="done", response={"text": "part"})
detail = store.detail(trace_id, since_seq=0)
assert detail["session"]["state"] == "done"
assert [e["event_type"] for e in detail["events"]] == ["model_request", "output_delta", "done"]
assert detail["session"]["response"] == {"text": "part"}
```

Also test `since_seq`, list filters/pagination, API/job/scheduler linking, per-event truncation marker, expired terminal cleanup, oldest-terminal budget cleanup, and that queued/running sessions survive cleanup.

- [ ] **Step 2: Run focused tests and confirm expected RED.**

Run: `python -m pytest -q tests/test_debug_traces.py`

Expected: FAIL because `local_ai_hub.debug_traces` and `DebugTraceStore` do not exist.

- [ ] **Step 3: Implement minimal SQLite store.** Use `traces` and `trace_events` tables with WAL, foreign keys, indexes on `(state, updated_at)`, `(trace_id, seq)`, and `(kind, created_at)`. Implement these exact methods:

```python
class DebugTraceStore:
    def start(self, *, kind, tenant, agent="", action="", source="", model="", request_id="", trace_id=None): ...
    def link(self, trace_id, *, request_id="", async_job_id="", scheduler_job_id=""): ...
    def event(self, trace_id, event_type, payload): ...
    def update(self, trace_id, **fields): ...
    def finish(self, trace_id, *, state, response=None, error=""): ...
    def list(self, *, kind="", state="", agent="", model="", limit=50, offset=0): ...
    def detail(self, trace_id, *, since_seq=0): ...
    def cleanup(self, *, now=None): ...
    def stats(self): ...
```

Store full debug fields in the trace database, never in telemetry. Enforce limits before writes; append one truncation event when a field/session cap is reached. Cleanup selects only terminal rows, deletes at most `cleanup_batch_size`, then checks database/WAL/SHM size and removes oldest terminal sessions until byte/count budgets hold. Attempt a short `wal_checkpoint(TRUNCATE)`; return counts instead of raising on lock/busy.

- [ ] **Step 4: Add defaults and rerun focused tests.** Add `[debug_traces]` values: `enabled=true`, `terminal_ttl_seconds=259200`, `max_bytes=268435456`, `max_sessions=1000`, `max_events_per_session=2000`, `max_event_bytes=65536`, `max_session_text_bytes=8388608`, `cleanup_batch_size=50`, `max_list_limit=100`. Keep async result TTL as fallback when trace TTL is omitted.

Run: `python -m pytest -q tests/test_debug_traces.py`

Expected: PASS.

## Task 2: Trace context and realtime model output

**Files:** modify `src/local_ai_hub/trace_context.py`, `ollama.py`, `tiered_ollama.py`, `services.py`, `tool_agent.py`; create/extend `tests/test_runtime_hardening.py` and `tests/test_ollama_tracing.py`.

- [ ] **Step 1: Write failing stream tests.** Feed NDJSON lines containing partial `response` text, `message.content`, a final `done` line, and malformed input. Assert callback receives bounded deltas and returned aggregate matches current non-streaming response shape. Assert no callback keeps current `request()` behavior.

```python
chunks = []
result = runtime.request_stream("/api/generate", payload, chunks.append)
assert "".join(chunks) == "hello"
assert result["response"] == "hello"
```

- [ ] **Step 2: Run tests and verify RED.**

Run: `python -m pytest -q tests/test_ollama_tracing.py`

Expected: FAIL because callback streaming API is absent.

- [ ] **Step 3: Implement bounded NDJSON streaming.** Add `OllamaRuntime.request_stream(endpoint, payload, on_chunk, timeout=None)`. Force `stream=True`, iterate response lines under the existing deadline, parse JSON, call `on_chunk` with only the new text, retain final metadata, and return the same aggregate dict expected by `services._generate`/`tool_agent`. A malformed line records an error in the return value but does not crash the worker. Add corresponding delegation to `TieredOllamaRuntime`.

- [ ] **Step 4: Add observer context and service/tool-agent hooks.** Extend `trace_context` with `set_observer`, `reset_observer`, and `observer` while preserving the four-token return contract of `set_context`. In `_generate` and the tool-agent loop, call observer methods for effective model payload, stream chunks, tool calls, and tool results. Use streaming only when observer exists; otherwise preserve `stream=False` and current response parsing.

- [ ] **Step 5: Run focused regression tests.**

Run: `python -m pytest -q tests/test_ollama_tracing.py tests/test_runtime_hardening.py tests/test_ollama_subagents.py`

Expected: PASS; existing untraced model behavior unchanged.

## Task 3: Async jobs and scheduler correlation

**Files:** modify `src/local_ai_hub/async_jobs.py`, `app.py`, `trace_context.py`; extend `tests/test_async_jobs.py`.

- [ ] **Step 1: Write failing lifecycle/link tests.** Assert submit creates a trace with original task/context, dispatch links scheduler `Job.id`, `_execute` emits `running`, model/tool events, and terminal state. Assert retry/cancel/recovery events are ordered and full prompt remains visible.

- [ ] **Step 2: Run focused tests and verify RED.**

Run: `python -m pytest -q tests/test_async_jobs.py`

Expected: FAIL on missing trace records/links.

- [ ] **Step 3: Integrate `DebugTraceStore` without changing async API contracts.** Inject store into `AsyncJobManager`; start a trace on new submit, link `async_job_id`, update/link scheduler `Job.id` after `enqueue`, and wrap executor execution in observer context. Record payload as `main_agent_prompt`, final response/error, retries, cancellation, and expiration. Coalesced submissions link to existing trace rather than creating duplicate work.

- [ ] **Step 4: Wire app lifecycle and bounded watchdog cleanup.** Construct the store before `AsyncJobManager`, pass it into services/jobs, call `debug_traces.cleanup()` once per watchdog interval, and add metadata-only trace cleanup stats to realtime status. Trace failures must be caught and never fail job execution.

- [ ] **Step 5: Run focused tests.**

Run: `python -m pytest -q tests/test_async_jobs.py tests/test_debug_traces.py`

Expected: PASS.

## Task 4: API request traces and authenticated endpoints

**Files:** modify `src/local_ai_hub/http_server.py`, `app.py`; extend `tests/test_http_phase_telemetry.py` and `tests/test_http_telemetry_outcomes.py`.

- [ ] **Step 1: Write failing HTTP trace tests.** Use the existing handler fixtures to assert a POST creates a trace containing request JSON, request ID/trace ID, agent/tenant/action, response, status, and stage events. Assert async submission links `async_job_id`; assert a trace read returns only after existing authorization succeeds.

- [ ] **Step 2: Run focused tests and verify RED.**

Run: `python -m pytest -q tests/test_http_phase_telemetry.py tests/test_http_telemetry_outcomes.py`

Expected: FAIL on missing trace records/endpoints.

- [ ] **Step 3: Capture request lifecycle safely.** In `_begin_trace`/POST body handling, create a trace for non-monitoring API requests, store the full body in the debug store, emit route/queue/handler/model/response events, and attach existing request/trace IDs. In `_send` and streamed response completion, store the final response/status and finish the session. Keep telemetry writes unchanged and catch trace-store failures.

- [ ] **Step 4: Add dashboard-only GET routes.** Implement authenticated endpoints with bounded query parameters:

```text
GET /v1/debug-traces?kind=&state=&agent=&model=&limit=&offset=
GET /v1/debug-traces/{trace_id}?since_seq=0
```

Return structured `not found`/`expired` errors. Do not expose these routes through MCP or tenant-facing async actions.

- [ ] **Step 5: Run focused tests.**

Run: `python -m pytest -q tests/test_http_phase_telemetry.py tests/test_http_telemetry_outcomes.py tests/test_async_jobs.py`

Expected: PASS.

## Task 5: Dashboard detail/history UX

**Files:** modify `src/local_ai_hub/dashboard.py`, `docs/DASHBOARD.md`, `docs/HTTP_API.md`; add dashboard string/route assertions to `tests/test_surface_and_packaging.py` or a focused `tests/test_debug_dashboard.py`.

- [ ] **Step 1: Write failing dashboard assertions.** Assert dashboard HTML contains trace-aware handlers for `jobs`, `activeReq`, and `recentReq`, the history endpoint, `since_seq`, live detail polling, and safe `<pre>` rendering.

- [ ] **Step 2: Run focused test and verify RED.**

Run: `python -m pytest -q tests/test_debug_dashboard.py`

Expected: FAIL until UI hooks exist.

- [ ] **Step 3: Implement trace-aware rows.** Preserve existing generic fallback. For rows with `trace_id`, open a detail panel showing summary, original main-agent prompt, effective model payload, event timeline, output, response/error, IDs, and timing. Active API, recent API, scheduler, and async rows use the same panel.

- [ ] **Step 4: Implement incremental polling/history.** Poll `/v1/debug-traces/{id}?since_seq=N` every second while state is `queued`/`running`; append events, update output, stop on terminal state. Add bounded history list with state/kind/agent/model filters and pagination. Escape all displayed values; use `textContent` or escaped HTML for trace content.

- [ ] **Step 5: Update docs and run focused tests.** Document full-content retention, authorization, TTL, budget cleanup, endpoint query limits, and active polling.

Run: `python -m pytest -q tests/test_debug_dashboard.py tests/test_surface_and_packaging.py`

Expected: PASS.

## Task 6: Full verification and review

**Files:** all changed files; no production scope expansion.

- [ ] **Step 1: Run indexed impact/review before validation.** Use Local AI Hub `local_ai_repo(action="review_diff")` and inspect only changed paths. Resolve any API/schema mismatch before running the suite.

- [ ] **Step 2: Run project validation through the command broker.**

Run:

```text
python -m compileall -q src mcp tools tests
python -m pytest -q
python tools/selftest.py
```

Expected: all commands exit 0. If a command is already in progress, reuse its cached result rather than launching a duplicate.

- [ ] **Step 3: Verify cleanup behavior with a temporary state directory.** Create enough completed traces to exceed TTL and byte/count budgets, call bounded cleanup repeatedly, and confirm each pass deletes only its configured batch, active sessions remain, and SQLite/WAL size converges below budget.

- [ ] **Step 4: Review final diff and workspace state.** Confirm no prompts/output/debug payloads entered telemetry/logs, no unbounded string accumulation remains, no temporary files were added, and docs match endpoint behavior. Workspace is not a Git repository, so report validation and leave commit creation to the repository owner.
