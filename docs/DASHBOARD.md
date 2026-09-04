# Dashboard

Open `/dashboard`. The shell contains no runtime data and can load before authentication; protected API calls require the configured token, stored only in browser session storage.

The dashboard provides overview/hardware/model/scheduler/cache/token-saving telemetry, preprocessing project control, Serena/CodeGraph status and session reset/rediscovery, architecture/dependency/dead-code analysis, bundle export/import, safe command classification/execution, doctor, log tail, database optimization, cache purge, validated runtime configuration overrides and hub/service controls. The architecture page exposes dependency audit and a separate source-security scan.

Overview shows agent HTTP latency separately from local-inference latency, policy rejections separately from operational failures, and avoided cloud tokens with estimated USD savings for the last 30 days. USD savings use the configurable blended rate `token_saving.cloud_token_cost_usd_per_million` (default: `$3.00` per million avoided tokens) and are explicitly estimates.

Command execution uses the same fail-closed broker as agents. The dashboard cannot turn an unknown or mutating command into an allowed validation command. Bundle import sends raw ZIP bytes to the bundle-specific limit.

Operational telemetry is metadata-only; repository/model payloads are not written to telemetry.

## Agent debug traces

The `Queue & requests` tab also contains bounded debug trace history for API requests, scheduler jobs and durable async workers. Clicking a linked row opens a dedicated authenticated trace page instead of a cramped modal: the sidebar lists runs, and the large detail pane shows a human-readable inspector. `Timeline` is the primary view, while `Prompt`, `Output`, `Events` and `Raw` are separate tabs. Each model step can be expanded to show its prompt, paired tool call/result and streamed output. The original request, final response/error and a compact status header remain available while a trace is queued or running; the detail view refreshes incrementally every second.

Debug traces are intentionally stored separately from operational telemetry in `server.state_dir/debug_traces.sqlite3`. Full prompt/output retention is enabled by default, but bounded by `[debug_traces]`: terminal TTL, maximum SQLite bytes, session count, events/session, event payload size and text/session. The watchdog removes only terminal traces, at most `cleanup_batch_size` per pass; live queued/running work is preserved. On startup, traces left queued/running by a previous process are closed as `failed` with `hub restarted`, so historical failures cannot look like active work. Adjust or disable this feature with the same config section.
# Tail latency

`Models & cache` now includes `HTTP tail latency`: p50/p95/p99 grouped by endpoint. Admission overload is visible as `admission`; policy rejections stay separate. The table stores metadata only and never prompts, source text, or model output.
