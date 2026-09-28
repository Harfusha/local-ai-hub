# Operations

Use `tools/hubctl.py status|watch`, `tools/doctor.py`, `tools/monitor.py`, and `tools/telemetry_report.py`. `tools/doctor.py` never auto-starts the hub, so an offline result is a real diagnostic state. The service supervisor is user-scoped and should have only one persistent instance. `/health` is suitable for liveness; model availability is intentionally not a health prerequisite.

In `doctor.py --json`, `runtime.code_intelligence_status` reports whether Serena diagnostics are available. Its `reason` distinguishes `hub_offline`, `status_unavailable`, and `diagnostics_not_reported`; these mean Serena state is unknown, not missing.

If Serena misbehaves, use the dashboard or `/api/code-intelligence/control` to rediscover its executable or reset its session. CodeGraphContext/KuzuDB is standalone external CLI/MCP tooling; configure and troubleshoot it through its own documentation, outside Hub. If derived indexes are corrupt, follow [Upgrade backup and rollback](#upgrade-backup-and-rollback) to snapshot the configured state directory first, then remove only derived cache/index databases; they are rebuildable.

## Upgrade backup and rollback

Before a release, preserve the prior code revision or wheel plus its runnable environment, copy the active `config.toml`, and back up each host MCP config the installer will merge. Resolve `server.state_dir` from the active config as `$stateDirBefore`; do not assume the default path. Record that path in the backup. After upgrade, resolve `server.state_dir` again as `$stateDirAfter`. Stop the service from its installation root with `python tools/hubctl.py stop`, then confirm `python tools/hubctl.py status` reports `running=false` before copying state.

Back up the entire `server.state_dir` to a new sibling directory outside it. State includes more than `agent_state.sqlite3`: durable stores include `async_jobs.sqlite3`, `work_orders.sqlite3`, `workspace_memory.sqlite3`, `learning.sqlite3`, `leases.sqlite3`, `evidence.sqlite3`, and `artifacts.sqlite3`; `work_journals/`, artifact payloads, SQLite `-wal`/`-shm` files, and future files must travel with them. A full-directory snapshot is the conservative rule; do not whitelist files or delete the original snapshot after rollout.

Windows PowerShell, with `$installRoot` set to the active code/venv root, `$stateDirBefore` and `$configPath` set from the active config, `$python` set to the active venv interpreter, and `$backupRoot` set outside both roots:

```powershell
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Path $backupRoot | Out-Null
robocopy $installRoot (Join-Path $backupRoot 'install') /E /COPY:DAT /DCOPY:DAT /R:1 /W:1
if ($LASTEXITCODE -ge 8) { throw "installation backup failed: robocopy exit $LASTEXITCODE" }
Copy-Item -LiteralPath $configPath -Destination (Join-Path $backupRoot 'config.toml')
Set-Content -LiteralPath (Join-Path $backupRoot 'state-dir-before.txt') -Value $stateDirBefore
& $python -m pip freeze --all | Set-Content -LiteralPath (Join-Path $backupRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw "pip freeze failed: exit $LASTEXITCODE" }
robocopy $stateDirBefore (Join-Path $backupRoot 'state-before') /E /COPY:DAT /DCOPY:DAT /R:1 /W:1
if ($LASTEXITCODE -ge 8) { throw "state backup failed: robocopy exit $LASTEXITCODE" }
```

Linux Bash with GNU coreutils, with `$install_root`, `$state_dir_before`, `$config_path`, and `$python` set to the active paths, and `$backup_root` set outside both roots:

```sh
set -euo pipefail
mkdir -p "$backup_root"
cp -a -- "$install_root" "$backup_root/install"
cp -a -- "$config_path" "$backup_root/config.toml"
printf '%s\n' "$state_dir_before" > "$backup_root/state-dir-before.txt"
"$python" -m pip freeze --all > "$backup_root/requirements.txt"
cp -a -- "$state_dir_before" "$backup_root/state-before"
```

Also copy every host MCP config that the installer will merge into `$backupRoot/host-configs` before running setup. Record each config's exact absolute path and whether it existed before the upgrade. After copying, run `PRAGMA integrity_check` against each `*.sqlite3` file in the backup copy. Keep the prior code/environment snapshot and host configs beside this state/config snapshot.

Rollback uses the saved code, config, host-config, and state snapshots as a unit. Run from outside `$installRoot`; set `$stateDirBefore` from `state-dir-before.txt`, resolve `$stateDirAfter` from the upgraded config, and use a unique `$stamp`. Stop the new service first. Before overwriting a post-upgrade host MCP config, preserve its current bytes under a unique `.failed-$stamp` name. Restore each saved host config to its recorded absolute path before starting an agent or regenerating MCP config. If a host config did not exist before setup, remove only the installer-created file at that path after checking that it has no post-upgrade user edits to preserve. On Windows:

```powershell
$ErrorActionPreference = 'Stop'
& $python (Join-Path $installRoot 'tools\hubctl.py') stop
if ($LASTEXITCODE -ne 0) { throw "service stop failed: exit $LASTEXITCODE" }
Move-Item -LiteralPath $installRoot -Destination "$installRoot.failed-$stamp"
robocopy (Join-Path $backupRoot 'install') $installRoot /E /COPY:DAT /DCOPY:DAT /R:1 /W:1
if ($LASTEXITCODE -ge 8) { throw "installation restore failed: robocopy exit $LASTEXITCODE" }
if (Test-Path -LiteralPath $stateDirAfter) { Move-Item -LiteralPath $stateDirAfter -Destination "$stateDirAfter.failed-$stamp" }
if (($stateDirBefore -ne $stateDirAfter) -and (Test-Path -LiteralPath $stateDirBefore)) { Move-Item -LiteralPath $stateDirBefore -Destination "$stateDirBefore.failed-$stamp" }
New-Item -ItemType Directory -Path (Split-Path -Parent $stateDirBefore) -Force | Out-Null
robocopy (Join-Path $backupRoot 'state-before') $stateDirBefore /E /COPY:DAT /DCOPY:DAT /R:1 /W:1
if ($LASTEXITCODE -ge 8) { throw "state restore failed: robocopy exit $LASTEXITCODE" }
Copy-Item -LiteralPath (Join-Path $backupRoot 'config.toml') -Destination $configPath -Force
```

On Linux Bash with GNU coreutils, use the same ordering with `$state_dir_before`, `$state_dir_after`, and a unique `$stamp`:

```sh
set -euo pipefail
"$python" "$install_root/tools/hubctl.py" stop
mv -- "$install_root" "$install_root.failed-$stamp"
cp -a -- "$backup_root/install" "$install_root"
if [ -e "$state_dir_after" ]; then mv -- "$state_dir_after" "$state_dir_after.failed-$stamp"; fi
if [ "$state_dir_before" != "$state_dir_after" ] && [ -e "$state_dir_before" ]; then mv -- "$state_dir_before" "$state_dir_before.failed-$stamp"; fi
mkdir -p "$(dirname -- "$state_dir_before")"
cp -a -- "$backup_root/state-before" "$state_dir_before"
cp -a -- "$backup_root/config.toml" "$config_path"
```

Restore the saved host MCP configs, then start the prior release and verify it with `doctor` and `hubctl status`. Until backward compatibility is proven against a migrated database, never start old code on new state: restore the pre-upgrade state snapshot as a unit. These steps preserve the failed installation/state for recovery and do not claim an automatic schema downgrade.

## Inference provider policy

`ollama.enabled = true` selects Ollama and prevents llama.cpp installation. With Ollama disabled, `llama_cpp.mode = "on"` installs and supervises the pinned llama.cpp runtime and Qwen 1.5B default under `server.state_dir`; `"auto"` checks a configured external loopback endpoint without downloading; `"off"` disables llama.cpp. SYCL startup on Windows Intel retries once on CPU. `hubctl status` and `doctor` show the selected provider and actual health; disabled providers are shown as disabled.

Bundles move preprocessed project state between Local AI Hub 4.0 installations; they are not source-code backups. Derived cache/index databases are disposable and are rebuilt when their current schema contract does not match.
## Latency and restart diagnostics

If a request becomes slow, inspect realtime runtime statistics before raising timeouts. Repository-state counters expose Git timeouts, degraded fingerprints and slow-root cooldowns. On a warm watched project, normal edits should invalidate only watcher-reported paths; a full preprocessing inventory is a periodic consistency pass, not a per-edit operation.

Repeated supervisor recycling during cold start should be investigated separately from runtime health failures. Cold-start and steady-state unhealthy grace windows are separate, the HTTP port is bound before application databases are opened, and admission-gate HTTP 503 is treated as alive-but-busy. This prevents duplicate startup and supervisor restart storms during transient overload.


## Overload and bounded failure behavior

HTTP handlers are admission-limited by `[server].max_concurrent_requests`; excess connections receive a small retryable 503 instead of allocating another handler thread. `[server].request_body_timeout_seconds` bounds slow request bodies. Model jobs have both a normal scheduler wait and `[scheduler].max_caller_wait_timeout_seconds`, so an omitted timeout cannot occupy a transport handler indefinitely. A failed model preparation opens a short model-specific cooldown and returns retryable unavailability rather than repeatedly attempting the same broken switch.

For cloud-agent p95/p99, separate endpoint duration from generation `queue_wait_ms` and `service_ms` in the telemetry tail table. If endpoint p95 is over an agent's foreground budget, send `delivery=auto` and `latency_budget_ms`; after ten endpoint samples the hub moves only that request to its durable low-priority queue. This is preferable to adding an unbounded fast lane: current admission rejects are already observable and async jobs keep long work out of occupied foreground handlers.

During a rollout, compare `scope=process` telemetry first. It is the post-restart/deploy cohort and exposes p95, p99 and failure rate by cloud agent, so a historical cold-start spike cannot hide a current regression. Compare it with the default rolling window only after the current cohort has enough requests; evaluation promotion remains report-only and needs ten matched opaque task IDs.

If `/api/context/pack` dominates a cloud-agent foreground SLO, have that agent choose `mode=fast` first. The result remains deterministic and carries a continuation hint for a deliberate later `mode=full` request. Do not raise client timeouts or create parallel full-context requests.

Hot-query preprocessing already warms deterministic, index and RAG capsules while idle; it cannot safely pre-generate historical model answers because prompts/output are deliberately not persisted. Repository artifacts are keyed by canonical parameters and watcher-backed root revision, while semantic reuse stays scoped to matching context identity. Use `batch_delegate` for independent local-model work and let the client coalesce identical active HTTP requests. An optional code-intelligence backend with a proven incomplete installation disables itself for that process; transient Serena failures cool down only the affected root and fall back to built-in indexes. Repair the external environment before the next hub restart instead of raising retry budgets.

SQLite-backed derived stores use short busy timeouts and bounded retries. A transient `locked`/`busy` result is treated as contention and degrades to a cache miss/write drop where safe; it is not treated as database corruption. If overload or another retryable response is returned, clients should back off rather than immediately duplicating the request.

Normal hub responses use HTTP/1.1 so clients may reuse loopback connections. Admission rejections intentionally close their socket and include both `Retry-After: 1` and JSON `retry_after_seconds: 1`; callers should wait rather than create retry storms.
 
## Agent Operating System operations
 
- State file: stored under `server.state_dir / agent_state.sqlite3`.
- Retention & cleanup: `agent_state_cleanup()` removes expired incidents, receipts, and unconfirmed memory candidates according to `retention_days` without removing active tasks.
- Controlled promotion: Promotion of memory to global scope or learning candidates to promoted status strictly requires explicit operator approval (`approver="user"`).
- Selective export: `export_bundle(agent_state_record_ids=[...])` validates that no unapproved global memory record or disallowed scope is exported, raising `BundleValidationError` on violation.
- Recovery: The event stream and SQLite state reopen on restart, replaying and validating snapshots.
