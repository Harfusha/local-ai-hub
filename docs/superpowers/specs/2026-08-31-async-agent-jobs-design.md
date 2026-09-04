# Persistent async agent jobs

## Goal

Allow an agent to submit a bounded local task, immediately receive a job id,
continue foreground work, and later obtain or cancel the result. Jobs survive
a hub restart without creating a second scheduler or terminal process.

## Public API

Extend `local_ai_task` with these actions:

- `submit`: validate a task request, deduplicate it, persist a queued job, and
  return `job_id` immediately.
- `status`: return compact state and progress metadata.
- `wait`: wait at most 90 seconds for a state transition or completion.
- `result`: return compact result preview plus an artifact id when complete.
- `cancel`: cancel a queued job or signal cancellation to a running job.

## Persistence and privacy

Use SQLite state under `server.state_dir` for job metadata, state, leases,
deduplication hashes, timestamps, TTL, and artifact references. Do not write
task prompts, source text, model output, secrets, or full paths to telemetry.
Payload and output remain in existing local artifact storage and use tenant
scoping. Expired job metadata and artifacts are removed by bounded cleanup.

## Scheduling and recovery

The existing scheduler owns execution. Async jobs have lower priority than
foreground work and yield when foreground work arrives. A durable lease marks
the running owner. On restart, queued jobs resume; an expired running lease is
returned to queued state once, then becomes terminally failed if it cannot
complete. Cancellation is cooperative and terminal.

## Cache and deduplication

The canonical request hash includes tenant, action, model routing inputs,
context fingerprint, and task parameters. A matching queued or running job is
returned instead of creating duplicate model work. Completed results still use
the existing exact and semantic caches before a job is created.

## Result contract

States are `queued`, `running`, `done`, `failed`, `cancelled`, and `expired`.
Every terminal response includes `retryable`; only transient scheduler/runtime
failures are retryable. `wait` never polls internally after its 90-second
bounded wait.
The API exposes no callbacks because MCP clients can safely call `wait` or
`status` while continuing independent work.

## Acceptance criteria

- Submit returns without waiting for model inference.
- Duplicate submissions coalesce across agents in one tenant.
- A foreground request preempts queued async work.
- Restart recovery neither loses queued jobs nor duplicates execution.
- Cancelled and expired jobs cannot return a successful result.
- Job prompts and outputs are absent from telemetry.
