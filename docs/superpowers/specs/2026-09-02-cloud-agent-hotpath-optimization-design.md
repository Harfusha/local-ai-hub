# Cloud-agent hot-path optimization design

## Goal

Improve the Local AI Hub path used by cloud coding agents without changing Qwen
model/offload/quantization settings: reduce avoidable context work, stop repeated
optional-index failures, and make restart-scoped p95/p99/cache evidence the
default operational view.

## Decisions

1. MCP `local_ai_repo(action="context")` uses deterministic cached `fast`
   context unless the caller explicitly requests `mode="full"`.  Full hybrid
   context remains available as an opt-in continuation, so retrieval quality is
   not silently reduced for cases that need it.
2. Both shipped MCP entrypoints use the same context-mode forwarding and expose
   telemetry with `scope="process"` by default.  The rolling 30-day view stays
   available with `scope="window"`.
3. The live dashboard defaults to process-scoped observability and lets the
   operator switch to the rolling window.  Its labels state the selected scope,
   avoiding misleading "30d" labels for live data.
4. Missing roots and permanently invalid external-project registrations become
   revision-scoped `skipped` states.  Transient backend failures remain
   `degraded` and can retry, preserving recovery behavior.
5. Do not lower semantic-cache thresholds or tune the scheduler without evidence:
   the new process cohort is the gate.  Change scheduling only after enough
   comparable requests show a p95/p99 or retry bottleneck.

## Acceptance

- Default MCP context posts `mode=fast`; explicit `full` remains full.
- Process telemetry is selectable through MCP and dashboard status.
- Dashboard state and labels follow the chosen scope.
- Repeated stale-root external indexing does not call the backend again for the
  same revision; ordinary backend errors still degrade.
- Focused and full validation pass.
