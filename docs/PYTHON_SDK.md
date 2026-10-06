# Python SDK

The `local-ai-hub` package includes a thin Python client at `local_ai_hub.client.HubClient`.

## Install

From a Local AI Hub checkout, install the core package:

```bash
python -m pip install .
```

For optional token economy tools, install `python -m pip install ".[token-economy]"`. The SDK does not require a separate client package.

Package extras are optional and do not change the `HubClient` API:

| Extra | Adds |
| --- | --- |
| `local-nlp` | Sentence Transformers for local NLP features. |
| `intel-accelerators` | `sentence-transformers[openvino]>=5.4,<6` and `openvino>=2026.1,<2027`. |
| `token-economy` | Token counting, prompt packing, AST search, and repository-map tools. |
| `performance` | Optional `orjson`, `msgspec`, and Cython accelerators. |
| `profiling` | `py-spy` and Scalene profiling tools. |
| `dev` | Pytest, Pyflakes, and coverage tools. |

Install multiple extras together, for example `python -m pip install ".[local-nlp,performance]"`. The base package remains sufficient for the Python client.

`HubClient` communicates with Local AI Hub only.

## Connect

```python
from local_ai_hub.client import HubClient

client = HubClient(tenant="example-agent", auto_start=False)
try:
    result = client.status(detail="brief")
    if result.get("success") is False:
        raise RuntimeError(result.get("error", "Local AI Hub request failed"))
    print(result)
finally:
    client.close()
```

`HubClient()` loads the normal Hub configuration and may start the configured local service when needed. Pass `config_path="..."` to select another config file, `tenant="..."` to set the request tenant, or `auto_start=False` when the application should only connect to an already-running service. `status()` returns a dictionary from the route selected by `detail`; `close()` releases the client's HTTP connection and does not stop the Hub service.

## Requests and timeouts

Use `get(path, timeout=15.0)` for GET requests and `post(path, payload=None, timeout=360.0, *, request_id=None, path_hints=None, tenant=None, cancel_event=None)` for POST requests. `request(path, payload=None, *, timeout=30.0, replay_safe=False, request_id=None, operational_action=None, requires_heavy_work=True, tenant=None, cancel_event=None)` exposes the lower-level request path; all options after `*` are keyword-only. Timeouts are capped by the configured `client.max_request_timeout_seconds` value.

`post("/api/search", payload, path_hints=...)` and `post("/api/command", payload, path_hints=...)` accept up to 64 validated hints when payload has no explicit `path`; an explicit `path` removes hints.

The client returns response dictionaries. Transport failures can include `success: false`, `outcome_unknown: true`, and a generated `request_id`: the server may have applied a mutating request before the connection failed. `request()` and `post()` also accept an optional caller-supplied request ID, validated as 1–128 visible ASCII characters without whitespace and sent in `X-LocalAI-Request-ID`. Automatic retries after transport loss are limited to read-only operations the client classifies as replay-safe. Replaying a mutation with the same ID is safe only where server journal coverage is verified. For an uncertain mutation, inspect resulting state before retry unless its coverage row confirms that contract.

`post()` classifies replay safety through a small, fail-closed allowlist of read-only POST paths/actions. Unknown or mutating POSTs are not resent automatically after transport loss. `request()` defaults to `replay_safe=False`; set it to `True` only when that exact operation is verified safe to repeat. For mutations, require verified server journal coverage before enabling replay. A caller-supplied `request_id` does not make an operation replay-safe. The client may retry a server-declared `in_progress` duplicate within the request deadline using the same ID; this is separate from replay after transport loss.

Use existing Hub API paths and payload schemas. The client is a transport wrapper, not a replacement for endpoint-specific validation or task/evidence verification.

`request()` performs a small local preflight before opening a socket. `POST /api/code/symbol` returns a terminal, non-retryable `symbol is required` result when `symbol` is blank (or `query` is blank when `symbol` is absent). `POST /api/review/diff` and `POST /api/repo/impact` return a terminal, non-retryable result when `root` resolves to an existing directory without a `.git` entry. These results include `preflight: true`; transport is not attempted.

## Convenience methods

`HubClient` exposes these public methods, grouped by role. Generic request methods are repeated above for orientation:

| Area | Methods |
| --- | --- |
| Connection and diagnostics | `close`, `ensure_server`, `status`, `doctor`, `logs`, `events`, `stream_events` |
| HTTP transport | `request`, `get`, `post` |
| Agent state, tasks, evidence, and memory | `coord`, `context_compile`, `verify_receipt`, `verify_completion`, `create_task`, `get_task`, `list_tasks`, `complete_task`, `fail_task`, `checkpoint_task`, `record_memory`, `find_memory` |
| Conversation | `continue_conversation` |
| Repository analysis | `circular_dependencies`, `generate_types`, `complexity`, `api_spec`, `dependency_slice`, `migration_drift`, `package_audit`, `git_diff`, `git_history_search`, `hotspots`, `generate_tests_for_diff`, `cross_repo_contract` |
| Other workflows | `diff_hunk_stage`, `flaky_detect`, `webhook_replay`, `eval_drift`, `mock_server`, `ingest_diagram`, `curate_training_dataset` |

The generated [API coverage inventory](API_COVERAGE.md) has a `HubClient method` row for each method and a `HubClient target` row for each HTTP target. Those rows record the payload, status, timeout, side-effect, and backend-availability evidence. A value marked `unverified` means the inventory lacks evidence; treat it as unknown.

### Method-to-request mapping

Convenience methods below call these Hub routes. `body` lists the wrapper's JSON keys; values come from the method arguments unless shown as a fixed action. For `coord()`, the selected route and body depend on `action`.

| Method(s) | Request target and body/query |
| --- | --- |
| `request`, `get`, `post` | Caller-supplied path; `request()` sends POST JSON, `get()` sends GET query parameters, and `post()` sends POST JSON. |
| `ensure_server` | Probes `GET /health`; it may start the configured service when no healthy instance answers. |
| `status` | When `detail="agent_state"`, uses `GET /api/status?detail=agent_state`; otherwise uses `GET /api/live/status?light=1&scope=…&detail=…`. |
| `doctor` | `GET /api/doctor`. |
| `logs` | `GET /api/logs/tail?lines=…` (clamped to 1–1000). |
| `events` | `GET /api/agent-state/events` with the supplied stream filters as query parameters. |
| `stream_events` | `GET /api/agent-state/events/stream`; SSE wait timeout defaults to 30 seconds and accepts cancellation. |
| `context_compile` | `POST /api/agent-state/context`; body contains action, task ID, token budget, changed paths, and `compact`; optional `since_hash` is sent when non-empty. |
| `verify_receipt`, `verify_completion` | `POST /api/agent-state/verification`; bodies contain respectively action + receipt, or action + task ID. |
| `create_task`, `get_task`, `list_tasks`, `complete_task`, `fail_task`, `checkpoint_task` | `POST /api/agent-state/tasks`; bodies select the action and carry task ID, goal, acceptance criteria, scope, filters, checkpoint, or reason as applicable. `create_task()` sends `action=create`, `goal`, `acceptance_criteria`, `task_id`, and `scope`, then merges any extra keyword fields into the body. |
| `record_memory`, `find_memory` | `POST /api/agent-state/memory`; action and memory fields come from the method arguments. |
| `continue_conversation` | `POST /api/conversations/continue`; body carries `conversation_id` and `task` (the `prompt` argument), plus optional `model`, `system`, `max_tokens`, and `temperature` settings. |
| `circular_dependencies` | `POST /api/repo/circular_dependencies`; body: `root`, `language`. |
| `generate_types` | `POST /api/repo/generate_types`; body: `root`, `file`, `write_stub`. |
| `complexity`, `hotspots` | `POST /api/repo/complexity` (`root`, `path`, `max_results`) and `POST /api/repo/hotspots` (`root`, `days`, `limit`). |
| `api_spec` | `POST /api/repo/api_spec`; body: `root`, `framework`. |
| `dependency_slice` | `POST /api/repo/dependency_slice`; body: `root`, `symbol`, `path`, `depth`. |
| `migration_drift`, `package_audit` | `POST /api/repo/migration_drift` (`root`, `db_path`) and `POST /api/repo/package_audit` (`root`, `lockfile_path`). |
| `git_diff`, `git_history_search` | `POST /api/git/diff` (`root`, `path`, `staged`, `max_lines`) and `POST /api/git/history_search` (`root`, `query`, `max_commits`). |
| `generate_tests_for_diff`, `cross_repo_contract` | `POST /api/repo/generate_tests_for_diff` (`root`, `diff`, `path`) and `POST /api/repo/cross_repo_contract` (`backend_root`, `frontend_root`). |
| `diff_hunk_stage`, `flaky_detect`, `webhook_replay`, `mock_server` | `POST /api/command/diff_hunk_stage` (`cwd`, `root`, `patch`); `/api/command/flaky_detect` (`cwd`, `root`, `command`, `runs`, `timeout`); `/api/command/webhook_replay` (`url`, `payload`, `secret`, `signature_header`); `/api/command/mock_server` (`action`, `root`, `spec_path`, `port`). |
| `eval_drift` | `POST /api/task/eval_drift`; body: `suite_name`. |
| `ingest_diagram` | `POST /api/rag/ingest_diagram`; body: `workspace`, `image_path`, `caption`, `metadata`. |
| `curate_training_dataset` | `POST /api/agent-state/tasks`; body: `action=curate_dataset`, `output_path`, `min_receipts`, `format`. |
| `coord` | Dispatches by action to the routes below. |

`coord()` action routes and body keys:

| Action | Request target and body |
| --- | --- |
| `task_*` | `POST /api/agent-state/tasks`; body: `action` plus action arguments. |
| `memory_*`, `relation_*` | `POST /api/agent-state/memory`; body: `action` plus action arguments. |
| `memo_put`, `memo_get`, `memo_search`, `memo_delete` | `POST /api/memory/put` (`root`, `key`, `value`, `ttl_seconds`); `/api/memory/get` (`root`, `key`); `/api/memory/search` (`root`, `query`, `limit`); `/api/memory/delete` (`root`, `key`). |
| `incident_decision`, `negative_knowledge_record`, `negative_knowledge_find` | `POST /api/agent-state/incidents`; body: action and action fields. |
| `context_compile` | `POST /api/agent-state/context`; body: action, task ID, token budget, changed paths, root, and optional context fields. |
| `verify_receipt`, `verify_completion` | `POST /api/agent-state/verification`; body: action, receipt or task ID, and optional root. |
| `claim`, `claim_batch` | `POST /api/leases/claim_batch`; body: `root`, `paths`, `ttl_seconds`, `purpose`. |
| `blackboard_*` | `POST /api/agent-state/blackboard`; body: action plus action arguments. |
| `release`, `leases` | `POST /api/leases/release` with `lease_id`; `GET /api/leases?root=…` for `leases`. |
| `worktree_lease`, `worktree_claim`, `worktree_release` | `POST /api/coord/worktree_lease` or `/api/coord/worktree_release`; body uses root, branch, and worktree fields as applicable. |
| `pubsub_publish`, `pubsub_poll` | `POST /api/coord/pubsub_publish` or `/api/coord/pubsub_poll`; body uses root, topic, message/publisher or cursor/limit fields. |
| `simulate_merge` | `POST /api/coord/simulate_merge`; body: `root`, `source_branch`, `target_branch`. |

All wrapper calls through `get()` use its 15-second default; calls through `post()` use 360 seconds. Both are capped by `client.max_request_timeout_seconds`; the wrappers do not declare per-method timeout overrides. `stream_events()` uses its own 30-second wait default. `ensure_server()` can start the configured local service; `close()` closes the client connection only. Other server-side effects and per-operation replay status are established only where the matching inventory row has evidence; `unverified` remains unknown.

## One-call workflows retained from T19

Each convenience method maps one client call to one endpoint. Calls through `post()` use its 360-second default, capped by `client.max_request_timeout_seconds`.

| Goal | Python call | Endpoint |
| --- | --- | --- |
| Callers | `client.callers(root, symbol, limit=50)` | `POST /api/repo/callers` |
| Context | `client.context_pack(root, query, max_tokens=4200, mode="adaptive")` | `POST /api/context/pack` |
| Receipt | `client.verify_receipt(task_id, criterion, evidence_id=...)` | `POST /api/agent-state/verification` |
| Conversation | `client.continue_conversation(conversation_id, prompt)` | `POST /api/conversations/continue` |
| Cancel job | `client.cancel_job(job_id)` | `POST /api/async-jobs` |
| Poll messages | `client.coord("pubsub_poll", root=root, topic=..., after_seq=0, limit=50)` | `POST /api/coord/pubsub_poll` |
| Resume task | `client.coord("task_resume", root=root, task_id=...)` | `POST /api/agent-state/tasks` |
| Evidence | `client.get_evidence(evidence_id, verify=True)` | `POST /api/evidence/get` |

Task resume: Sets task status to `ACTIVE` and preserves checkpoint metadata; does not restore workspace files.

The older T19 receipt stated **8/8 successful workflows on first direct call; 8 HTTP requests total**. That is historical evidence, not acceptance for this merged revision. Polling now uses the integer `after_seq` cursor; the former `since_timestamp` example and assertions require updating. Do not infer that a count of returned messages proves cursor semantics or live cross-tenant isolation.

Recovery: `context mode must be adaptive, full or fast` requires a supported mode. `conversation not found` requires an existing conversation. If a continuation is already running (`in_progress=true`, `retryable=true`), wait for it to finish; do not send a duplicate request. Inspect current task or job state before retrying.

## Effects and retries

Convenience methods delegate to Hub endpoints. The method name or HTTP verb alone does not establish all server-side effects. `ensure_server()` may start the configured service; `close()` releases the client connection and does not stop that service. Check the matching coverage row before relying on an operation's side effects or replay safety. Methods using `get()` inherit its 15-second default; methods using `post()` inherit its 360-second default; both remain capped by configuration. `stream_events()` has its own wait behavior.

`post()` applies the client's replay-safety policy for known endpoint and payload combinations. `request(..., replay_safe=True)` is a caller assertion that the operation can be safely replayed. If a mutating call returns `outcome_unknown`, inspect its state first. When an operation has verified same-ID journal support, retry only with unchanged method, path, payload, and `request_id`.

## Common workflows

Each row shows the SDK call for the first operation; follow-up calls appear where needed. Use valid task, conversation, job, and evidence IDs from earlier successful responses.

| Scenario | SDK call |
| --- | --- |
| Find callers | `client.post("/api/repo/callers", {"root": root, "symbol": symbol, "limit": 50})` |
| Build repository context | `client.post("/api/context/pack", {"root": root, "query": task, "task_id": task_id, "phase": "edit"})` |
| Verify a change | `client.verify_receipt(task_id, criterion, passed=True, evidence_id=evidence_id, details=details)`; then `client.verify_completion(task_id)` only when checking task-level completion |
| Continue a conversation | `client.continue_conversation(conversation_id, prompt)` |
| Cancel an asynchronous job | `client.post("/api/async-jobs", {"action": "cancel", "job_id": job_id})` |
| Resume a task | `client.coord("task_resume", task_id=task_id)` |
| Retrieve evidence | `client.post("/api/evidence/get", {"evidence_id": evidence_id, "verify": True})` |

These calls return the Hub response dictionary directly. Check `success` before using a result; on failure, retain its `error`, `terminal`, `retryable`, and `retry_after_seconds` fields. A transport error may include `outcome_unknown` and `request_id`, so inspect operation state before replaying a mutation.

## Release evidence

This guide describes the Python source API. It does not prove package installation, clean-host update, MCP adapter/daemon revision identity, live model availability, or runtime quality. See [T19 Release Validation Runbook](T19_RELEASE_VALIDATION_RUNBOOK.md); clean-host lifecycle evidence remains pending T04 blocker clearance, T20's frozen revision, and an assigned serial slot.
