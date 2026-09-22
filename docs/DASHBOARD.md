# Dashboard

Open `/dashboard`. The shell contains no runtime data and can load before authentication; protected API calls require the configured token, stored only in browser session storage.

The dashboard provides overview/hardware/model/scheduler/cache/token-saving telemetry, preprocessing project control, Serena/CodeGraph status and session reset/rediscovery, architecture/dependency/dead-code analysis, bundle export/import, safe command classification/execution, doctor, log tail, database optimization, cache purge, validated runtime configuration overrides and hub/service controls. The architecture page exposes dependency audit and a separate source-security scan.

Overview shows agent HTTP latency separately from local-inference latency, policy rejections separately from operational failures, and end-to-end token-efficiency accounting. The headline is a signed net cloud-token delta: an explicitly measured source/context baseline (or response-compaction baseline when no stronger source baseline exists) minus the estimated tokens the cloud agent spends emitting the MCP tool call and reading the projected tool response. Deterministic/RG-like candidate sizes remain diagnostics unless a producer proves the cloud-side baseline. Calls that cost more context than they save therefore appear as negative overhead instead of being hidden. Overlapping raw → packed → projected reductions are not added together; the visible tool response is charged once. The enabled-tool schema catalog is shown separately as a conservative schema-adjusted upper-bound because hosts differ in how often schema text is injected/reused. Local cache/single-flight compute avoidance is a separate metric and is never added to cloud-context savings. USD savings price saved cloud input and output tokens separately with `token_saving.cloud_input_token_cost_usd_per_million` and `token_saving.cloud_output_token_cost_usd_per_million`, while preserving the same additive-safe baseline selection; the blended rate remains a fallback for older rows without channel counters.

Command execution uses the same fail-closed broker as agents. The dashboard cannot turn an unknown or mutating command into an allowed validation command. Bundle import sends raw ZIP bytes to the bundle-specific limit.

Operational telemetry is metadata-only; repository/model payloads are not written to telemetry.

## Agent debug traces

The `Queue & requests` tab also contains bounded debug trace history for API requests, scheduler jobs and durable async workers. Clicking a linked row opens a dedicated authenticated trace page: the sidebar lists runs, and the detail pane shows a human-readable inspector instead of a cramped modal.

Each trace uses a request-specific primary presentation. Useful result-oriented content is visible immediately; reasoning, context, raw payloads and implementation metadata are kept in focused expandable sections.

- **Model chat:** prompt, final response, capture state and tool-call/result summaries are shown first. Thinking, model context, request envelope and the chronological execution timeline are expandable.
- **Agent loop:** the current objective, progress/status, final result or error, and meaningful step summaries are shown first. Context, correlations, per-step metadata and raw events are expandable.
- **Command:** command, arguments, status, exit information and useful stdout/stderr are shown first. Environment, internal identifiers, raw input and full event data are expandable.
- **Review:** review status, summary, finding counts and actionable finding text are shown first. Finding metadata, evidence payloads and raw review data are expandable.
- **Repository intelligence:** the operation, result summary, matches or relationships, and useful answer are shown first. Evidence slices, graph payloads, ranking metadata and raw response data are expandable.
- **RAG search:** the query, result count, ranked result summaries and useful snippets are shown first. Full evidence, payloads, retrieval metadata and raw response data are expandable.
- **Async job:** job status, progress, queue wait, retry state, live/incomplete state, result or error are shown first. Worker input/output, timing, identifiers and raw job data are expandable.
- **Request/response:** method, path/action, status, duration, request body, response body and error are shown first. Headers, correlations, actor/tenant, retained bytes, timing and raw transport data are expandable.

Primary views omit empty or none-like values, internal identifiers and duplicate metadata. Secrets are redacted, while retained payload content is shown in full without display-only truncation markers. Malformed, empty, queued, running, live and incomplete traces get an explicit state or safe generic fallback so the available input, output or error remains visible. The original request, final response/error and compact status header remain available while a trace is queued or running; the detail view refreshes incrementally every second. Technical summary, event timeline, correlations, tabs and raw JSON remain available as optional expandable details, not as a prerequisite for understanding the result.

Debug traces are intentionally stored separately from operational telemetry in `server.state_dir/debug_traces.sqlite3`. Full prompt/output retention is enabled by default, but bounded by `[debug_traces]`: terminal TTL, maximum SQLite bytes, session count, events/session, event payload size and text/session. The list endpoint shows 200 traces by default; raise `debug_traces.max_list_limit` in `config.toml` for a larger history. The watchdog removes only terminal traces, at most `cleanup_batch_size` per pass; live queued/running work is preserved. On startup, traces left queued/running by a previous process are closed as `failed` with `hub restarted`, so historical failures cannot look like active work. Adjust or disable this feature with the same config section.
# Tail latency

`Models & cache` now includes `HTTP tail latency`: p50/p95/p99 grouped by endpoint. Admission overload is visible as `admission`; policy rejections stay separate. The table stores metadata only and never prompts, source text, or model output.
