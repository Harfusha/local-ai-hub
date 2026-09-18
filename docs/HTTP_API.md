# HTTP API

Authenticated dashboard-only debug endpoints expose bounded execution history:

* `GET /api/debug-traces?kind=&state=&agent=&model=&limit=&offset=` lists trace summaries. `limit` is capped by `debug_traces.max_list_limit`.
* `GET /api/debug-traces/{trace_id}?since_seq=0` returns session detail and ordered events after the supplied sequence number, allowing incremental realtime polling.

Trace detail may include the original API request, effective model prompt/payload, streamed model output, tool calls/results and final response. It is stored separately from metadata-only telemetry in `server.state_dir/debug_traces.sqlite3`; retention is bounded by the `[debug_traces]` TTL, byte, session, event and text limits. Cleanup deletes only terminal traces in small batches and never deletes queued/running sessions.

The service defaults to `127.0.0.1:11435`. `/health` is a lightweight liveness endpoint. Runtime/status endpoints include `/api/status`, `/api/capabilities`, `/api/live/status`, metrics/telemetry, hardware status, models, leases and preprocessing.

Repository endpoints cover profile/map/code-index/deterministic/search/context, code symbols/diagnostics/AST, import resolution, dependency/security/test/refactor/dead-code/callgraph analysis and git status. Code-intelligence queries use `/api/code-intelligence/query`; session management uses `/api/code-intelligence/control`.

`local_ai_repo(action="context")` and `POST /api/context/pack` share the adaptive context contract. For non-trivial work, pass `task_id` or `phase`, or `guarded: true`; this is default-on guidance for agent integrations. Omit those fields to preserve legacy `fast`/`full` behavior.

Guarded request fields are `task_id`, `phase`, `focus`, `preload_profile`, `changed_paths`, `base`, `staged`, `since_hash`, `approval`, `override_reason`, and `token_budget`. Supported phases are `plan`, `edit`, `review`, `test`, and `handoff`. The response includes a bounded `adaptive_context_pack`/`context_pack`, `context_id`, `repo_revision`, `stale`, `evidence_ids`, `warnings`, and (when supplied) `delta_from`/`since_hash` metadata. A matching revision/hash may be reused as an unchanged delta pack; callers should keep the prior useful pack and avoid duplicate discovery.

Every warning is a concise JSON object: `severity`, `code`, `message`, `evidence_ids`, `affected_paths`, `recommended_action`, and `requires_approval`. Use `info`, `warning`, `boundary`, and `high-risk` as severity levels. `boundary` and `high-risk` warnings are recoverable soft-stops: the task may enter `waiting` until approval. Ordinary warnings require an `override_reason`; decisions are persisted only when Agent OS is enabled.

Fallback behavior remains useful and explicit:

* Missing preload file: omit that input and emit `code: "preload_missing"` with deterministic context intact.
* Unavailable Serena/CodeGraphContext: use deterministic/indexed search and emit `code: "code_intelligence_unavailable"`.
* Local-model timeout/failure: return deterministic/indexed evidence and emit `code: "local_model_timeout"` or `"local_model_unavailable"`; model text cannot override evidence.
* Disabled Agent OS: return a stateless repository pack and emit `code: "agent_state_disabled"`; no memory, decision, task, or receipt is persisted.
* Unchanged delta: return `unchanged: true` or equivalent `delta_from` metadata and retain the previous useful pack.
* Legacy caller: omit guarded fields and receive the existing fast/full response shape.

Memory promotion requires explicit approval. Relevant repository revision changes mark affected memory `stale`; stale/conflicting records remain available as diagnostics, not authoritative context, until revalidated. Evidence IDs and repository revision must be preserved through local-model composition and post-processing.

Operational endpoints cover doctor, DB optimization, cache purge, log tail and service control. Bundles export as ZIP and import only as raw `application/zip` or `application/octet-stream`. Commands must pass `/api/command` policy classification.

JSON requests require a JSON content type and bounded `Content-Length`; malformed JSON returns 400 and oversized bodies 413. Authenticated deployments use `X-LocalAI-Token`. Errors are JSON objects with `success:false` where applicable.

Model-backed endpoints `/api/delegate`, `/api/reason`, `/api/review`, `/api/second-opinion`, `/api/compress`, `/api/route`, and `/api/delegate/batch` accept optional `delivery` (`sync`, `async`, `auto`) and `latency_budget_ms`. `sync` remains the default. `async` immediately returns the existing durable async-job response. `auto` defers only when fresh endpoint p95 history has at least ten observations and exceeds a positive budget; otherwise it remains synchronous and reports the decision in `delivery`. Generation responses may include rounded `latency.queue_wait_ms` and `latency.service_ms` metadata for tail-latency diagnosis.

`POST /api/delegate` and `POST /api/reason` accept `conversation:true` only with `delivery:"sync"`. A successful first turn returns opaque `conversation_id`. Send the next message to `POST /api/conversations/continue` with `conversation_id`, `task`, and optional `context`. Conversations are tenant-bound, bounded, process-memory only and lost on restart; profiles and durable async jobs are not supported.

Agent Operating System endpoints project durable task, memory, incident, verification and context state:

* `GET /api/agent-state/tasks?task_id=&status=&limit=` lists or inspects tasks.
* `POST /api/agent-state/tasks` supports actions: `create` (goal, acceptance criteria, scope, risk profile), `get` (task_id), `transition` (status: planned, active, waiting, blocked, verifying, completed, failed, abandoned), `complete` (auto-advances through verification gates if criteria met), `fail` (records failure reason), `checkpoint` (phase, next_action, affected_paths, evidence_ids), `resume`, and `list`.
* `GET /api/agent-state/memory?record_id=&scope=&key=&query=&status=&limit=` searches or fetches memory records.
* `POST /api/agent-state/memory` supports actions: `record` (kind, scope, key, value, evidence_ids, confidence), `get` (record_id), `find` (scope, key, query, status, limit), `promote` (record_id, target_scope), and `supersede` (old_record_id, new_record_id, reason).
* `POST /api/agent-state/incidents` supports actions: `record` (tool failure fingerprint), `find` (lookup matching negative knowledge), and `decision` (circuit-breaker / tool retry guidance).
* `POST /api/agent-state/verification` supports actions: `receipt` (records criterion verification proof: passed, evidence_id, command_id) and `completion` (evaluates whether all task acceptance criteria have passing receipts).
* `POST /api/agent-state/context` supports action `compile` (assembles bounded context window with active task, checkpoint, relevant memories, negative knowledge, and leases).
* `POST /api/agent-state/learning` supports actions: `create_candidate`, `promote`, `observe` (SLO feedback), and `list`.
* `POST /api/agent-state/cleanup` runs bounded retention cleanup of stale events and snapshots.
* `GET /api/status?detail=agent_state` provides a lightweight overview of active tasks, memory counts, incidents, and health status.

Retry only an explicitly retryable response, honor `retry_after_seconds`, keep the same request ID for the logical replay, and do not run client-side polling loops. The hub itself coalesces active async jobs and uses per-backend cooldowns for optional code-intelligence runtimes.

The endpoint implementation in `src/local_ai_hub/http_server.py` is the normative contract; the compact MCP interface is the preferred agent integration.
