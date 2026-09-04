# Agent and API Debug Traces

## Goal

Make background agent jobs and API requests inspectable from the dashboard. A user can open an active or completed row and see the originating request, the prompt sent by the main agent, the effective model request, lifecycle stages, tool activity, streamed output, response, timing, and errors.

The feature covers async worker jobs shown in the scheduler queue, active API requests, and recent API requests. It does not add an MCP tool or change the compact MCP surface.

## Scope and privacy

The dashboard debug trace is explicitly configured to retain full request prompts, contexts, model payloads, tool payloads/results, streamed output, and final responses. This is separate from normal observability telemetry. The existing telemetry remains metadata-only.

All trace endpoints require the existing dashboard/API authorization. Trace content is never written to logs or telemetry events. Payloads are bounded and stored only under the configured `server.state_dir`.

## Architecture

Add a shared `DebugTraceStore` backed by SQLite WAL under `server.state_dir`. It owns trace sessions and ordered trace events for both API requests and async jobs.

Each session contains:

- stable trace/session ID, optional API request ID, optional async job ID, optional scheduler job ID;
- kind (`api_request` or `async_job`), agent, tenant, action, source, model;
- state, created/updated/finished timestamps, queue/inference/total timing;
- bounded request, effective model payload, accumulated output, response, and error fields.

Each event contains a monotonic sequence number, timestamp, stage/type, and bounded JSON payload. Event types include `request_received`, `queued`, `running`, `model_request`, `output_delta`, `tool_call`, `tool_result`, `response`, `done`, `failed`, and `cancelled`.

Instrumentation uses the existing request and execution flow:

1. HTTP handling creates or attaches a trace session at request start and records the request body and metadata.
2. Async job submission links the API trace, async job, and scheduler job when IDs are available. The original sanitized task/context remains visible as the main-agent prompt.
3. Service/tool-agent execution records the effective system/user messages or generate payload before model execution.
4. Traced model calls use the existing Ollama NDJSON capability with a callback. Chunks are persisted as `output_delta` events and accumulated into the session without changing the final response contract. Untraced calls retain current non-streaming behavior.
5. Completion, failure, cancellation, retry, and response delivery close or update the trace session.

The scheduler status response keeps its existing compact rows. Dashboard-only GET endpoints expose trace history and detail, including incremental events using `since_seq`. No new worker process is introduced.

## Dashboard behavior

Scheduler queue rows, active API request rows, and recent API request rows become trace-aware clickable rows. Clicking opens one detail panel with:

- live state and timing summary;
- original main-agent request/prompt;
- exact effective model payload;
- live output and tool call timeline;
- final response or error;
- linked API, async, and scheduler IDs.

For active sessions, the panel polls the detail endpoint every second with the last event sequence. It stops polling after terminal state. Completed sessions remain available in the history list for their retention period. Existing generic details for rows without a trace remain available.

History supports state, agent, model, and kind filters plus bounded pagination. Rendering uses text-safe escaping and `<pre>` blocks; trace content never becomes HTML.

## Incremental disk cleanup

Trace retention must not grow the disk without bound.

- Terminal sessions expire after configurable `terminal_ttl_seconds` (default follows the current async result TTL).
- A configurable hard database budget (`max_bytes`) and maximum event/session counts apply to the combined trace database files.
- Cleanup runs from the existing bounded watchdog, not in request/worker critical paths.
- Every pass deletes at most a small configurable batch of oldest expired terminal sessions/events, then enforces the byte/count budgets by deleting the oldest terminal traces first.
- Queued and running sessions are never removed by retention cleanup. Their individual prompt/output/event limits still apply while active.
- Large fields and output deltas are capped per event and per session. When a cap is reached, the store records a truncation marker and continues lifecycle tracking.
- After deletes, SQLite WAL checkpoint/truncate is attempted within a short bounded operation. Busy/locked cleanup is skipped and retried on the next watchdog pass.
- Cleanup exposes deleted session/event counts and current approximate bytes in status, without exposing trace content.

This makes cleanup gradual, avoids a large blocking purge, and bounds both logical trace volume and on-disk growth.

## Error handling and compatibility

- Trace persistence failure never fails the underlying API request or worker job; execution continues with a bounded diagnostic counter.
- Streaming parse/network failure records an error event and preserves the existing final error handling.
- Missing or expired trace returns a structured not-found/expired response.
- Existing async status/result/cancel actions retain their current behavior.
- Tenant authorization remains enforced for agent-facing async APIs; dashboard trace access uses the existing dashboard authorization boundary.

## Verification

Tests will cover:

- trace session/event creation, ordering, linking, and incremental `since_seq` reads;
- full prompt/effective payload/output visibility with escaping;
- streamed output accumulation and terminal state transitions;
- API request and async job correlation;
- active polling stopping at terminal state;
- pagination and filters;
- per-event/per-session truncation;
- incremental cleanup batches, TTL expiry, byte/count budgets, live-session protection, and bounded WAL cleanup;
- trace-store failures not changing request/job success;
- existing async job, dashboard, and HTTP behavior remaining compatible.
