# Operations

Use `tools/hubctl.py status|watch`, `tools/doctor.py`, `tools/monitor.py`, and `tools/telemetry_report.py`. `tools/doctor.py` never auto-starts the hub, so an offline result is a real diagnostic state. The service supervisor is user-scoped and should have only one persistent instance. `/health` is suitable for liveness; model availability is intentionally not a health prerequisite.

If Serena or CodeGraph misbehaves, use the dashboard or `/v1/code-intelligence/control` to rediscover executables or reset sessions. If derived indexes are corrupt, stop the hub, back up any needed state and remove only derived cache/index databases; they are rebuildable.

For an upgrade within the 1.x line, preserve `config.toml` and repository source, replace application files, rerun setup and doctor, then refresh preprocessing. Bundles are for moving preprocessed project state between compatible installations, not for source-code backup.
## Latency and restart diagnostics

If a request becomes slow, inspect realtime runtime statistics before raising timeouts. Repository-state counters expose Git timeouts, degraded fingerprints and slow-root cooldowns. On a warm watched project, normal edits should invalidate only watcher-reported paths; a full preprocessing inventory is a periodic consistency pass, not a per-edit operation.

Repeated supervisor recycling during cold start should be investigated separately from runtime health failures. Version 1.5 keeps separate cold-start and steady-state unhealthy grace windows, binds the HTTP port before opening application databases, and treats admission-gate HTTP 503 as alive-but-busy. This prevents duplicate startup and supervisor restart storms during transient overload.


## Overload and bounded failure behavior

HTTP handlers are admission-limited by `[server].max_concurrent_requests`; excess connections receive a small retryable 503 instead of allocating another handler thread. `[server].request_body_timeout_seconds` bounds slow request bodies. Model jobs have both a normal scheduler wait and `[scheduler].max_caller_wait_timeout_seconds`, so an omitted timeout cannot occupy a transport handler indefinitely. A failed model preparation opens a short model-specific cooldown and returns retryable unavailability rather than repeatedly attempting the same broken switch.

For cloud-agent p95/p99, separate endpoint duration from generation `queue_wait_ms` and `service_ms` in the telemetry tail table. If endpoint p95 is over an agent's foreground budget, send `delivery=auto` and `latency_budget_ms`; after ten endpoint samples the hub moves only that request to its durable low-priority queue. This is preferable to adding an unbounded fast lane: current admission rejects are already observable and async jobs keep long work out of occupied foreground handlers.

During a rollout, compare `scope=process` telemetry first. It is the post-restart/deploy cohort and exposes p95, p99 and failure rate by cloud agent, so a historical cold-start spike cannot hide a current regression. Compare it with the default rolling window only after the current cohort has enough requests; evaluation promotion remains report-only and needs ten matched opaque task IDs.

If `/v1/context/pack` dominates a cloud-agent foreground SLO, have that agent choose `mode=fast` first. The result remains deterministic and carries a continuation hint for a deliberate later `mode=full` request. Do not raise client timeouts or create parallel full-context requests.

Hot-query preprocessing already warms deterministic, index and RAG capsules while idle; it cannot safely pre-generate historical model answers because prompts/output are deliberately not persisted. Repository artifacts are keyed by canonical parameters and watcher-backed root revision, while semantic reuse stays scoped to compatible context. Use `batch_delegate` for independent local-model work and let the client coalesce identical active HTTP requests. An optional code-intelligence backend with a proven incomplete installation disables itself for that process; transient Serena/CodeGraph failures cool down only the affected root and fall back to built-in indexes. Repair the external environment before the next hub restart instead of raising retry budgets.

SQLite-backed derived stores use short busy timeouts and bounded retries. A transient `locked`/`busy` result is treated as contention and degrades to a cache miss/write drop where safe; it is not treated as database corruption. If overload or another retryable response is returned, clients should back off rather than immediately duplicating the request.

Normal hub responses use HTTP/1.1 so compatible clients may reuse loopback connections. Admission rejections intentionally close their socket and include both `Retry-After: 1` and JSON `retry_after_seconds: 1`; callers should wait rather than create retry storms.
 
## Agent Operating System operations
 
- State file: stored under `server.state_dir / agent_state.sqlite3`.
- Retention & cleanup: `agent_state_cleanup()` removes expired incidents, receipts, and unconfirmed memory candidates according to `retention_days` without removing active tasks.
- Controlled promotion: Promotion of memory to global scope or learning candidates to promoted status strictly requires explicit operator approval (`approver="user"`).
- Selective export: `export_bundle(agent_state_record_ids=[...])` validates that no unapproved global memory record or disallowed scope is exported, raising `BundleValidationError` on violation.
- Recovery: The event stream and SQLite state reopen on restart, replaying and validating snapshots.
