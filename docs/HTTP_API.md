# HTTP API

Authenticated dashboard-only debug endpoints expose bounded execution history:

* `GET /v1/debug-traces?kind=&state=&agent=&model=&limit=&offset=` lists trace summaries. `limit` is capped by `debug_traces.max_list_limit`.
* `GET /v1/debug-traces/{trace_id}?since_seq=0` returns session detail and ordered events after the supplied sequence number, allowing incremental realtime polling.

Trace detail may include the original API request, effective model prompt/payload, streamed model output, tool calls/results and final response. It is stored separately from metadata-only telemetry in `server.state_dir/debug_traces.sqlite3`; retention is bounded by the `[debug_traces]` TTL, byte, session, event and text limits. Cleanup deletes only terminal traces in small batches and never deletes queued/running sessions.

The service defaults to `127.0.0.1:11435`. `/health` is a lightweight liveness endpoint. Runtime/status endpoints include `/v1/status`, `/v1/capabilities`, `/v1/live/status`, metrics/telemetry, hardware status, models, leases and preprocessing.

Repository endpoints cover profile/map/code-index/deterministic/search/context, code symbols/diagnostics/AST, import resolution, dependency/security/test/refactor/dead-code/callgraph analysis and git status. Code-intelligence queries use `/v1/code-intelligence/query`; session management uses `/v1/code-intelligence/control`.

Operational endpoints cover doctor, DB optimization, cache purge, log tail and service control. Bundles export via JSON control request and import as raw `application/zip` (preferred) or validated base64 JSON for API compatibility. Commands must pass `/v1/command` policy classification.

JSON requests require a JSON content type and bounded `Content-Length`; malformed JSON returns 400 and oversized bodies 413. Authenticated deployments use `X-LocalAI-Token`. Errors are JSON objects with `success:false` where applicable.

Model-backed endpoints `/v1/delegate`, `/v1/reason`, `/v1/review`, `/v1/second-opinion`, `/v1/compress`, `/v1/route`, and `/v1/delegate/batch` accept optional `delivery` (`sync`, `async`, `auto`) and `latency_budget_ms`. `sync` remains the default. `async` immediately returns the existing durable async-job response. `auto` defers only when fresh endpoint p95 history has at least ten observations and exceeds a positive budget; otherwise it remains synchronous and reports the decision in `delivery`. Generation responses may include rounded `latency.queue_wait_ms` and `latency.service_ms` metadata for tail-latency diagnosis.

Retry only an explicitly retryable response, honor `retry_after_seconds`, keep the same request ID for the logical replay, and do not run client-side polling loops. The hub itself coalesces active async jobs and uses per-backend cooldowns for optional code-intelligence runtimes.

The endpoint implementation in `src/local_ai_hub/http_server.py` is the normative contract; the compact MCP interface is the preferred agent integration.
