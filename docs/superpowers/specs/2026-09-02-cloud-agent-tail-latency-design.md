# Cloud-agent tail-latency design

## Scope

Improve cloud-agent reliability, cache reuse, and tail latency. Model selection, offload,
and configuration for every Qwen 3.5 and Qwen 2.5 model stay untouched.

## Decisions

1. A duplicate server request waits briefly for the original recovery-journal entry.
   Completed work is replayed; unfinished work returns one explicit `in_progress` result.
2. Repository caches remain keyed by canonical operation parameters and watcher revision.
   Existing stale-on-error behavior is retained; no stale result is presented as fresh.
3. Scheduler foreground priority and idle-only background work are retained. New changes
   must not introduce a foreground/background model-routing change.
4. HTTP validates code-intelligence and symbol inputs before any index or external backend
   call. Invalid input is a terminal client result, not an operational error or retry.
5. Serena and CodeGraph transient failures open a circuit only for the affected root.
   A broken CodeGraph installation remains a process-wide permanent fallback.
6. Evaluation records can be attached to ordinary cloud-agent requests through an explicit
   opaque `evaluation` payload. Hub records request duration automatically; promotion
   remains report-only and still requires paired quality and test evidence.

## Safety

- No prompt, source, model output, or full project path enters telemetry.
- Waiting is bounded by `resilience.singleflight_wait_timeout_seconds`.
- All rejected inputs return `terminal: true`, `retryable: false`.
- No model routing or Qwen configuration changes.

## Verification

Focused tests cover recovery wait/replay, schema rejection, per-root circuit isolation,
and automatic hub-on evaluation duration. Full compile, test, and self-test run after edits.
