# Dashboard

Open `/dashboard` on the local Hub. The dashboard identifies its requests as the local dashboard client. It has no token form, credential storage, token query parameter, or interactive authentication prompt. Optional server authentication for integrations remains a separate server contract.

The dashboard has ten pages: Overview, Queue & requests, Agent OS, Projects, Commands, Models & RAG, Reliability & Logs, Configuration, Bundles, and Live events. Their controls cover telemetry and estimates, request/trace inspection, durable tasks/memory/incidents, registered projects, running-command statistics and worktrees, model/RAG statistics and the prompt arena, logs, runtime overrides, bundles, and event filtering. Controls also expose diagnostics, activity modes and maintenance actions. CodeGraphContext/KuzuDB are standalone external tools, not Hub services or dashboard backends.

Agent OS requires an explicit repository selection and Refresh. Its reads and mutations carry that root; authorization and client/tenant isolation stay on the server. Actions remain disabled until scoped data loads. Task-scoped memory requires a Task ID; new memory defaults to repository scope. A failed incident/task/memory request is shown as unavailable rather than an empty list.

Incident retrieval uses the supported `find` action. Retired resolve/ignore controls are absent; the current public incident contract supports scoped retrieval and recording prevention rules.

Removed pages do not retain their old handlers: architecture graph/scans, model installation, SQL explorer, command-entry console, and the separate Agent OS SSE panel. Aggregate adoption polling was also removed because its destination panel no longer exists. The current Live events page uses the bounded `/api/live` poller; durable trajectory paging remains available in Agent OS. Regression checks reject literal DOM references without a rendered target.

Overview shows agent HTTP latency separately from local-inference latency, policy rejections separately from operational failures, and end-to-end token-efficiency accounting. The headline is a signed net cloud-token delta: an explicitly measured source/context baseline (or response-compaction baseline when no stronger source baseline exists) minus the estimated tokens the cloud agent spends emitting the MCP tool call and reading the projected tool response. Deterministic/RG-like candidate sizes remain diagnostics unless a producer proves the cloud-side baseline. Calls that cost more context than they save therefore appear as negative overhead instead of being hidden. Overlapping raw → packed → projected reductions are not added together; the visible tool response is charged once. The enabled-tool schema catalog is shown separately as a conservative schema-adjusted upper-bound because hosts differ in how often schema text is injected/reused. Local cache/single-flight compute avoidance is a separate metric and is never added to cloud-context savings. USD savings price saved cloud input and output tokens separately with `token_saving.cloud_input_token_cost_usd_per_million` and `token_saving.cloud_output_token_cost_usd_per_million`, while preserving the same additive-safe baseline selection; the blended rate remains a fallback for older rows without channel counters.

Command statistics reflect the same fail-closed broker used by agents. Worktree inspection requires an explicit repository selection; it never defaults to the first registered project. Bundle import sends raw ZIP bytes to the bundle-specific limit.

Operational telemetry is metadata-only; repository/model payloads are not written to telemetry.

The metrics period selector applies to historical telemetry in Overview, Models & RAG and Reliability: since restart or the last 30 days. It does not change live runtime checks, current queues, command counters or scoped Agent OS records. Missing or stale telemetry displays `Unavailable`; cumulative dropped records and writer errors mark estimates incomplete without changing current runtime health. An observed zero remains a zero, with `No accounted calls yet` when no tool-accounting evidence exists. Small USD estimates retain four decimal places. Open **How token savings are estimated** for baseline sources, protocol cost, schema exposure, local compute reuse, pricing rates and writer health. Process-session history uses the same signed tool-accounting delta as the overview, rather than local inference context reduction.

The dark layout shares readable typography, consistent controls, visible keyboard focus and responsive cards. Configuration controls stay disabled until the current settings load; failed loading leaves saving disabled and allows a reload.

Status metadata refreshes in the background before its 15-second validity window expires, so the 30-day telemetry aggregation can exceed the short per-probe deadline without blanking every subsequent poll. Expired results remain unavailable. Project inventory failures are shown explicitly, bulk controls stay disabled until status recovers, and project counts are displayed separately from concurrent preprocessing capacity.

Rolling-window token and USD totals use persistent daily accounting plus raw records for the partial first UTC day, without adding the same events twice. Pruning retained request details therefore does not erase accumulated savings. If raw records for the partial boundary day were pruned, the estimate is marked incomplete rather than reconstructing unknown amounts. Latency/request/cache samples and the detailed baseline-source breakdown use retained records and are labeled accordingly. Events that failed to persist before the schema repair cannot be recovered from these aggregates.

If another request is building the first status snapshot, the overview shows `warming`, keeps prior rendered status when available, and retries through its bounded poll backoff.

## Agent debug traces

Queue & requests links retained requests to their traces. Agent OS → Run History & Inspect also exposes the trace list, separately from durable task trajectories. Clicking a linked row opens a dedicated trace page with a history sidebar.

The current inspector shows Input and Output first, with separate Copy controls and explicit missing-content states. Metrics show only recorded values. Command/project settings, summary, reasoning, timeline, correlations and raw JSON live in expandable technical details. The selected technical tab, open details and scroll position survive refreshes. Large content loads through bounded content/event pages; older/newer event navigation remains explicit. Superseded standalone presentation helpers are not required to view a trace.

Debug traces are intentionally stored separately from aggregate operational telemetry in `server.state_dir/debug_traces.sqlite3`. Detailed request/input/output capture is disabled by default and can be toggled live in the dashboard. While enabled, complete endpoint payloads are stored locally without redaction or content truncation; dashboard summaries may redact credential-shaped values for display, while authorized detail inspection remains local. Large SSE output is appended incrementally to avoid buffering the stream in application memory. Retention TTL, total SQLite bytes and session count bound storage by deleting whole terminal traces; trace content is never trimmed. The list endpoint shows 200 traces by default; raise `debug_traces.max_list_limit` in `config.toml` for a larger history. The watchdog removes only terminal traces, at most `cleanup_batch_size` per pass; live queued/running work is preserved. On startup, traces left queued/running by a previous process are closed as `failed` with `hub restarted`, so historical failures cannot look like active work. Adjust or disable this feature with the same config section.
# Tail latency

`Models & RAG` includes `HTTP tail latency`: p50/p95/p99 grouped by endpoint. Admission overload is visible as `admission`; policy rejections stay separate. The table stores metadata only and never prompts, source text, or model output.

## UI coverage and limits

UI verification covers all ten navigation pages, Agent OS subtabs, search/filter/reset states, project registration and configuration reset dialogs (cancelled), worktree selection, bundle import without a file, request/trace inspection and responsive layouts. Regression tests cover unavailable and partial data, rejected operations and retired controls. Diagnostics and destructive maintenance, project deletion, imports with real data, configuration saves and model inference require separate operational verification; opening their controls is not evidence that these actions succeeded.

## Current state versus history

Current runtime health uses service state, online probes, heartbeat, current blocked requests/open issues and current non-telemetry dependency checks. Request failures, policy rejections, inference retries, supervisor restarts, unclean exits and cumulative writer errors remain historical diagnostics. A failed period-specific telemetry query makes metrics unavailable; it does not establish a runtime outage. Stale live status cannot establish healthy current operation.

The scope audit covers all ten pages:
- Overview separates current checks from recorded failures and identifies Hub-wide Agent OS inventory. Enabled feature flags do not establish subsystem health; unreported flags remain unknown.
- Queue & requests distinguishes live scheduler/API work from retained request history. The failed-history shortcut applies the failed filter and clears conflicting filters; it cannot reconstruct pruned requests.
- Agent OS uses selected repository/client records. Trajectory paths and receipts are labeled as such, rather than invented step counts; reported token zero stays zero.
- Projects distinguishes global enablement from active processing. Complete progress does not prove later file synchronization or watcher health.
- Commands identifies counters since restart and registered/locked/prunable worktrees without implying that every checkout is actively used.
- Models & RAG identifies selected-period aggregates. Charts record distinct status snapshots, clear on period changes/unavailable data, and do not claim instantaneous latency or throughput. Chunk presence does not prove index readiness; arena generation speed and end-to-end rate have distinct labels.
- Reliability keeps live health independent from retained failures and up to 100 sessions started within 30 days. Unclean exit means no clean shutdown was recorded; cause remains unknown. The dashboard no longer exposes the misleading Resolve all errors action, which rewrote failure history rather than repairing causes. Existing historical data is preserved.
- Configuration edits remain separate from loaded runtime state and require Save; load failures leave editing disabled.
- Bundles does not declare an errored project ready merely because progress is 100 percent.
- Live events distinguishes explicit success, failure, warning and informational events with no reported result.

## Shared visual layout

All ten primary pages have a clear page heading and short purpose statement. Content uses a bounded desktop width, consistent typography, spacing, form fields and keyboard focus. Configuration options use labeled cards; advanced capability details are collapsed on Overview. Long repository identities wrap, tables scroll inside their panels and mobile events use compact two-row records. Empty repository selection is a neutral prompt, separate from failed loading. Request outcomes identify operation failure even when HTTP delivery returned 200.

Visual checks cover the deployed dashboard at desktop and phone widths. Passing source/script regressions does not establish that destructive maintenance, configuration saves, imports or model benchmarks were executed.
