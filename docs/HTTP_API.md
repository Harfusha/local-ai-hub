# HTTP API

Patch and repair operations forward verification receipts produced by the command
broker. A successful command without a receipt reports
`verification_receipt_warning`; it does not mint fallback evidence or establish
task completion. Completion still requires the persisted command, artifact,
actual task owner, repository revision and receipt checks.

Project RAG operations (`/api/rag/index`, `/api/rag/search`,
`/api/rag/ingest_document`, `/api/rag/ingest_diagram`) require an explicit
absolute authorized `root`. Each workspace is bound to that real repository
root; supplying another project's workspace rejects before reading or writing
its contents. Diagram files must remain inside that root without symlink or
junction traversal. Owner-global docsets retain their separate namespace.

`POST /api/route` uses the canonical string fields `query` and `text`; `task` and `context` are rejected rather than treated as aliases. The MCP `local_ai_task(action="route")` adapter translates its canonical `task` and `context` fields to `query` and `text` at the HTTP boundary. `POST /api/reason` uses `problem` and optional `context`; `task` is rejected as an alias. `POST /api/review` uses `code` and optional `instructions`; `context` is rejected as an alias. The corresponding `local_ai_task` adapters translate `task` and `context` at the HTTP boundary.

Authenticated dashboard-only debug endpoints expose bounded execution history:

* `GET /api/debug-traces?kind=&state=&agent=&model=&limit=&offset=` lists trace summaries. `limit` is capped by `debug_traces.max_list_limit`.
* `GET /api/debug-traces/{trace_id}?since_seq=0&limit=100&max_bytes=8388608` returns session detail and one ordered event page. `since_seq` is exclusive; `next_seq` is the continuation cursor; `has_more` reports remaining events. `limit` is clamped to 1–1000. HTTP `max_bytes` is clamped to 1 KiB–8 MiB; the default and hard ceiling are 8 MiB. Each JSON response stays within the reported `max_bytes`. A page that cannot fit returns HTTP 413 with `error_code=trace_detail_oversize`, unchanged `next_seq`, `oversize_seq` and `required_bytes`. Forward cursors clamp to SQLite's signed integer range; past-end pages remain empty rather than resetting to retained history. Pruned prefixes appear in `gap_ranges`. The dashboard retrieves large trace fields through bounded content pages and loads older/newer event history with `before_seq` and `since_seq`. The T18 pin-90 report is a historical failure snapshot; current tests and runtime acceptance remain unverified.
* `GET /api/agent-state/events/stream?stream_id=&after_seq=` streams Agent OS events. The integrated ordered-state implementation uses numeric SSE sequence IDs with an explicit stream filter, a fixed replay high-water mark, bounded replay pages, and explicit queue-gap metadata. T18 composite/global reconnect cursors remain preserved in the checkpoint but are not integrated; use `stream_id` and `after_seq` for replay.

Trace detail may include the original API request, effective model prompt/payload, streamed model output, tool calls/results and final response. Page-by-page retrieval preserves full event payloads; events that do not fit the requested page budget are never silently dropped. It is stored separately from metadata-only telemetry in `server.state_dir/debug_traces.sqlite3`; retention is bounded by the `[debug_traces]` TTL, byte, session, event and text limits. Cleanup deletes only terminal traces in small batches and never deletes queued/running sessions.

The service defaults to `127.0.0.1:11435`. `/health` is a lightweight liveness endpoint. Runtime/status endpoints include `/api/status`, `/api/capabilities`, `/api/live/status`, metrics/telemetry, hardware status, models, leases and preprocessing.

`GET /api/telemetry/report?error_limit=25&error_cursor=` starts a stable error-group snapshot; continue with returned `report.error_fingerprints_page.next_cursor`. Cursor pages order by fingerprint, type, component and operation; cursor carries an event-ID watermark and fixed cutoff, so later writes or rolling-window expiry do not move groups mid-walk. Normal telemetry retention cleanup can still remove expired rows. `error_offset` remains for legacy callers; do not combine it with a cursor. Malformed or mixed cursors return HTTP 400.
Status cache responses report `snapshot_cached` and `status_age_ms`. A concurrent request during a cold snapshot build returns `success:false`, `degraded:true`, and `snapshot_warming:true`; retry after `retry_after_ms`. A request during refresh can receive a cached snapshot marked `snapshot_stale:true`. Master admin authorization and result audit paths are retained. Successful async-job submissions, idempotent replays, and coalesced submissions report `durability: "sqlite_committed"` only after the SQLite transaction commits. For a lost response, retry with the same caller-supplied `request_id` to recover the persisted job instead of creating a duplicate.

Operational mode is persisted in the configured state directory as `active`, `gaming`, or `maintenance`. `GET /api/mode` reports the current mode; authenticated loopback `POST /api/mode` coordinates admission and transition work. `hubctl mode <mode>`, `hubctl pause`, and `hubctl resume` use the live API when the Hub is healthy, without starting it; when it is offline, they update the shared state file directly. The dashboard connection badge shows mode, revision, and degraded state. Gaming permits explicitly classified deterministic and cheap read-only agent actions, including async-job status, wait, result, cancel, and evaluation reports. Maintenance rejects agent MCP actions except the operator health tool, and rejects agent HTTP `POST` actions before request tracing or route handling. This includes cheap reads, async-job controls, and evaluation reports. Mode, health, telemetry-report, control, and dashboard operator paths remain available. Both paused modes block model-backed MCP work. Gaming unload requests are best-effort; CUDA cache requests and model-reference drops do not prove physical VRAM release.

When inference or preprocessing is active, a gaming transition persists the mode and reports unload as deferred; running work is not force-terminated. The service does not queue an automatic unload retry after that work finishes, so an operator must repeat `POST /api/mode` once the Hub is quiescent. A timed-out in-process release returns at its deadline, but its daemon worker may continue holding model locks until reference destruction completes. These results do not prove physical GPU memory release.

Repository endpoints cover profile/map/code-index/deterministic/search/context, code symbols/diagnostics/AST, import resolution, dependency/security/test/refactor/dead-code/callgraph analysis and git status. Code-intelligence queries use `/api/code-intelligence/query`; session management uses `/api/code-intelligence/control`.

`local_ai_repo(action="context")` and `POST /api/context/pack` share the adaptive-only context contract. For non-trivial work, pass `task_id` or `phase`, or `guarded: true`; this is default-on guidance for agent integrations. Omitted mode selects `adaptive`; other values reject before retrieval.

Guarded request fields are `guarded`, `task_id`, `phase`, `focus`, `preload_profile`, `changed_paths`, `base`, `staged`, `since_hash`, `approval`, `override_reason`, and `token_budget`. Supported phases are `plan`, `edit`, `review`, `test`, and `handoff`. The response includes a bounded `adaptive_context_pack`/`context_pack`, `context_id`, `repo_revision`, `stale`, `evidence_ids`, `warnings`, `model_warnings`, and (when supplied) `delta_from`/`since_hash` metadata. A matching revision/hash may be reused as an unchanged delta pack; callers should keep the prior useful pack and avoid duplicate discovery.

Every guarded warning is a concise JSON object: `severity`, `code`, `message`, `evidence_ids`, `affected_paths`, `recommended_action`, and `requires_approval`. Context-compiler fallback warnings may be smaller and contain `code`, `message`, plus relevant path/error details. Use `info`, `warning`, `boundary`, and `high-risk` as severity levels. `boundary` and `high-risk` warnings are recoverable soft-stops: the task may enter `waiting` until approval. Ordinary warnings require an `override_reason`; decisions are persisted only when Agent OS is enabled.

Fallback behavior remains useful and explicit:

* Missing preload file: omit that input and emit `code: "preload_missing_file"` with deterministic context intact.
* Deterministic fallback within adaptive retrieval: set `degraded: true`, `context_source: "deterministic-fast"`, and `continuation.available: true` with `continuation.mode: "adaptive"`.
* Unavailable optional semantic/code-intelligence backend: keep deterministic/lexical evidence and report `semantic_used: false` when no semantic results are used; no synthetic warning code is added.
* Guarded local-model relevance failure: keep deterministic/indexed evidence and set `model_degraded: true` plus `model_degraded_reason` (`no_authoritative_evidence`, `model_error`, `model_unavailable`, `invalid_model_output`, or `relevance_error`); model text cannot override evidence.
* Guarded response degradation fields are `degraded`, `context_source`, `continuation`, `model_degraded`, `model_degraded_reason`, `warnings`, and `model_warnings`.
* Disabled Agent OS: return a stateless repository pack and emit `code: "agent_state_disabled"`; no memory, decision, task, or receipt is persisted.
* Unchanged delta: return `unchanged: true` or equivalent `delta_from` metadata and retain the previous useful pack.
* Context packs accept only `adaptive`; unknown and retired modes return a terminal validation error.

Memory promotion requires explicit approval. Relevant repository revision changes mark affected memory `stale`; stale/conflicting records remain available as diagnostics, not authoritative context, until revalidated. Evidence IDs and repository revision must be preserved through local-model composition and post-processing.

Operational endpoints cover doctor, DB optimization, cache purge, log tail and service control. Bundles export as ZIP and import only as raw `application/zip` or `application/octet-stream`. Validation commands use the agent host's bounded native command tool and its authorization controls; no public command execution endpoint is exposed.

JSON requests require a JSON content type and bounded `Content-Length`; malformed JSON returns 400 and oversized bodies 413. Authenticated deployments use `X-LocalAI-Token`. Errors are JSON objects with `success:false` where applicable.

`POST /api/memory/put` accepts optional non-negative integer `expected_version`. Version `0` denotes a key with no prior writes; each write advances that key's generation, and deleting a stored memo advances its retained generation so delete-and-recreate cannot reset the version. Expiration hides a memo but does not advance its generation; a writer holding the last generation may recreate the key unless a later write or deletion has advanced it. A stale version returns `success:false`, `version_conflict:true`, and `current_version` without changing the memo. Omitting the field preserves last-writer-wins behavior. Memory `get` and `search` responses include the current version; a missing `get` also returns the retained generation.

Aggregate MCP response budget defaults to approximately 3200 tokens. Explicit `max_response_tokens` values below 128 are rejected with a bounded terminal error; they are never silently increased.

Model-backed endpoints `/api/delegate`, `/api/reason`, `/api/review`, `/api/second-opinion`, `/api/compress`, `/api/route`, and `/api/delegate/batch` accept optional `delivery` (`sync`, `async`, `auto`) and `latency_budget_ms`. `sync` remains the default. `async` immediately returns the existing durable async-job response. `auto` defers only when fresh endpoint p95 history has at least ten observations and exceeds a positive budget; otherwise it remains synchronous and reports the decision in `delivery`. Generation responses may include rounded `latency.queue_wait_ms` and `latency.service_ms` metadata for tail-latency diagnosis.

For `/api/review/diff`, a positive `review.max_queue_age_ms` exceeded by the request's queue age takes precedence and returns a terminal 503 bypass. Otherwise, a positive latency budget with fewer than five telemetry samples selects async with reason `cold_start_review_diff`. Conversations reject `async` and `auto` and require `delivery="sync"`.

`POST /api/delegate` and `POST /api/reason` accept `conversation:true` only with `delivery:"sync"`; initial and continued task text must be nonblank. A successful first turn returns an opaque `conversation_id`. Send the next message to `POST /api/conversations/continue` with `conversation_id`, `task`, and optional `context`. Conversation IDs are not authorization credentials; access still requires the configured route credentials. The initial model, route, system prompt, output limit, and temperature stay pinned. Only one turn can be active; a concurrent continuation returns retryable in-progress status.

Conversations allow 12 user turns by default and a prompt limit from `model_conversations.max_prompt_tokens`, falling back to `token_saving.max_local_input_tokens` or 56,000 tokens. Defaults are 900 seconds idle TTL, 1,800 seconds active TTL, and capacity 1,000. State and transcripts stay in process memory, are not recovered after restart, and are lost when the process exits. Profiles and durable async jobs are not supported for conversations.

Agent Operating System endpoints project durable task, memory, incident, verification and context state:

* `GET /api/agent-state/events?stream_id=&after_seq=0&through_seq=&limit=100` returns ordered event pages. HTTP `limit` is clamped to 1–100 and each UTF-8 JSON response is capped at 1 MiB. Pass first page `last_seq` unchanged as inclusive `through_seq` on subsequent pages. `next_seq` is the last returned event; use it as exclusive `after_seq`. Oversize first events return HTTP 413 without cursor advancement.
* `GET /api/agent-state/tasks?task_id=&status=&limit=&include_stale=&query=` lists or inspects tasks. `query` case-insensitively matches task ID, owner, goal, acceptance criteria, and checkpoint phase/action/paths/blockers. Query scans inspect at most 10,000 candidates; a response may set `query_truncated: true` when more candidate tasks remain beyond that window.
* `POST /api/agent-state/tasks` supports actions: `create` (goal, acceptance criteria, scope, risk profile), `get` (task_id), `transition` (status: planned, active, waiting, blocked, verifying, completed, failed, abandoned), `complete` (auto-advances through verification gates if criteria met), `fail` (records failure reason), `checkpoint` (phase, next_action, affected_paths, evidence_ids), `resume`, and `list` (optional string `query`, status, limit, and include_stale filters).
* `GET /api/agent-state/memory?record_id=&scope=&key=&query=&status=&limit=` searches or fetches memory records.
* `POST /api/agent-state/memory` supports actions: `record` (kind, scope, key, value, evidence_ids, confidence), `get` (record_id), `find` (scope, key, query, status, limit), `promote` (record_id, target_scope), and `supersede` (old_record_id, new_record_id, reason).
* `POST /api/agent-state/incidents` supports actions: `record` (tool failure fingerprint), `find` (lookup matching negative knowledge), and `decision` (circuit-breaker / tool retry guidance).
* `POST /api/agent-state/verification` supports actions: `receipt` (records criterion verification proof: passed, evidence_id, command_id) and `completion` (evaluates whether all task acceptance criteria have passing receipts).
* `POST /api/agent-state/context` supports action `compile` (assembles bounded context window with active task, checkpoint, relevant memories, negative knowledge, and leases).
* `POST /api/agent-state/learning` supports actions: `create_candidate`, `promote`, `observe` (SLO feedback), and `list`.
* `POST /api/agent-state/cleanup` runs bounded retention cleanup of stale events and snapshots.
* Agent OS tasks and memory use `/api/agent-state/tasks` and `/api/agent-state/memory` with an explicit authorized repository root. Compact MCP readiness uses `local_ai_status(detail="brief")`.

Retry only an explicitly retryable response, honor `retry_after_seconds`, keep the same request ID for the logical replay, and do not run client-side polling loops. The hub itself coalesces active async jobs and uses per-backend cooldowns for optional code-intelligence runtimes.

The endpoint implementation in `src/local_ai_hub/http_server.py` is the normative contract; the compact MCP interface is the preferred agent integration.




# Existing task budget increases

`POST /api/agent-state/tasks` with `action="budget_increase"` uses ordinary
write authorization, including canonical loopback access without an API token.
No special owner/admin credential is required. Supply the existing `task_id`,
an authorized absolute `root`, a nonempty `reason`, and nested `budget` limits.
Every supplied maximum must strictly increase; omitted maxima and all consumed
counters remain unchanged. The broker verifies persisted task scope and records
the actual transport actor plus before/after values atomically with the update.
Caller-supplied owner or authorization overrides reject. Increasing a failed
task's limits preserves its status and owner; resume is a separate action.
