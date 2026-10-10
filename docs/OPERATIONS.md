# Operations

Use `tools/hubctl.py status|watch`, `tools/doctor.py`, `tools/monitor.py`, and `tools/telemetry_report.py`. `tools/doctor.py` never auto-starts the hub, so an offline result is a real diagnostic state. Target shared runtime uses one per-user Hub install, one configured `server.state_dir`, and one user-level supervisor/daemon for all Codex chats and worktrees under that OS account. Every enabled agent uses a lightweight stdio proxy. Acceptance: clean install registers exactly one user service; update reuses or reconciles that same registration. Never install or register a daemon per agent, chat, repository, or worktree. The generated global Codex `local-ai` entry starts `python -m local_ai_hub.mcp_server` as a stdio adapter; each active Codex MCP session may own one adapter process. The adapter forwards Hub calls through `HubClient` over HTTP. It creates bounded protocol/metadata helpers, but must not create `LocalAIApp`, `HubServices`, `ProjectPreprocessor`, `CodeIndex`, `RAGStore`, or model pools. Multiple adapter processes do not prove duplicate daemons; inspect parent/command line and the OS service identity. The single per-user supervisor starts the HTTP daemon at logon/session startup. Global Codex `cwd=install_dir` is not the caller's project root, and setup injects no project-root environment. Repository-scoped repo/RAG MCP actions now reject missing or `.` roots at the adapter boundary; preprocessing likewise requires an explicit absolute root. Always pass the caller's explicit project root. Release acceptance still requires installed-runtime and deployment proof for this source-level guard. T03/T04/T13 integration remains pending in this T19 candidate; treat this as release acceptance contract, not current runtime proof. Project-local entries use `target_root` as `cwd`; global entries use `install_dir`. Every global repository, task, or memory request must set `root` to the caller's project root and preserve task context; both MCP API and `HubClient` must send it explicitly. Never infer root from `install_dir` or process cwd. The current candidate does not validate caller roots against `allowed_roots` or derive tenant from root. HTTP uses the supplied `X-LocalAI-Tenant`/`X-Tenant-ID` label, falling back to `http-default`; labels are not authorization. On loopback, an empty API token leaves data/control routes unauthenticated. Non-loopback binds and remote control endpoints are unsupported; the HTTP server stays loopback-only. T13 root/auth integration remains pending and unverified.

Offline clients return structured transport errors. `request_not_sent` means request body was not transmitted; `outcome_unknown` means delivery may have occurred and must not be replayed. T04 error classification remains pending integration in this candidate. Use supervisor status/restart for recovery; do not launch per-agent daemon processes.

Open the dashboard with `python tools/hubctl.py dashboard`, which prints the configured URL. Default endpoint is `http://127.0.0.1:11435/dashboard`. Enter a configured API token in the dashboard toolbar for the browser session; never put it in the URL. After an update or reboot, check `python tools/hubctl.py service-status`, `python tools/hubctl.py status`, `/health`, and the dashboard before reopening agent clients.

The server accepts only `127.0.0.1`; remote access and anonymous HTTP API access are unsupported. Configure one `security.api_token` for protected routes. Send it with `X-LocalAI-Token` or `Authorization: Bearer`. Optional permissions are `monitor`, `read`, `write`, and `admin`; optional `api_token_tenant` binds the token to one tenant. `/health` is public liveness, `/dashboard` is a public static shell, and `/ready` requires `monitor` permission.

If Serena misbehaves, use the dashboard or `/api/code-intelligence/control` to rediscover its executable or reset its session. If derived indexes are corrupt, stop the hub, back up any needed state and remove only derived cache/index databases; they are rebuildable.

## Shared-daemon install, update, and acceptance matrix

This is the parent-GO acceptance sequence. Commands below are documented, not executed. Use one canonical source/install tree and one user-level service for all chats/worktrees under that OS account.

| Platform | Clean-host install | Update existing per-user install | Expected service identity and read-only check |
|---|---|---|---|
| Windows | From a clean source checkout: `powershell -ExecutionPolicy Bypass -File ".\install.ps1" -Profile auto` | After the clean-tree, fast-forward-only update in [UPDATE_PROMPT.md](UPDATE_PROMPT.md): `powershell -ExecutionPolicy Bypass -File "$HOME\.local-ai-hub\install.ps1" -Profile auto` | Task Scheduler `LocalAIHubSupervisor`; query with `schtasks /Query /TN LocalAIHubSupervisor /FO LIST`. Run-key fallback only if task registration is unavailable; check `Get-ItemProperty HKCU:\Software\Microsoft\Windows\CurrentVersion\Run -Name LocalAIHubSupervisor -ErrorAction SilentlyContinue`. Exactly one startup registration. |
| macOS | From a clean source checkout: `./install.sh --profile auto` | `bash "$HOME/.local-ai-hub/install.sh" --profile auto` | LaunchAgent `~/Library/LaunchAgents/com.localai.hub.plist`, label `com.localai.hub`; check `launchctl print "gui/$(id -u)/com.localai.hub"`. |
| Linux | From a clean source checkout: `./install.sh --profile auto` | `bash "$HOME/.local-ai-hub/install.sh" --profile auto` | systemd user unit `~/.config/systemd/user/local-ai-hub.service`; check `systemctl --user show local-ai-hub.service --property=LoadState,ActiveState,UnitFileState`. |

After install/update, run status checks from the canonical installation. Windows PowerShell:

```powershell
$hub = Join-Path $HOME ".local-ai-hub"
& (Join-Path $hub ".venv\Scripts\python.exe") (Join-Path $hub "tools\hubctl.py") service-status
& (Join-Path $hub ".venv\Scripts\python.exe") (Join-Path $hub "tools\hubctl.py") status
Invoke-RestMethod "http://127.0.0.1:11435/health"
```

macOS/Linux shell:

```bash
hub="$HOME/.local-ai-hub"
"$hub/.venv/bin/python" "$hub/tools/hubctl.py" service-status
"$hub/.venv/bin/python" "$hub/tools/hubctl.py" status
curl --fail http://127.0.0.1:11435/health
```

Restart once with the matching user Python:

```powershell
$hub = Join-Path $HOME ".local-ai-hub"
& (Join-Path $hub ".venv\Scripts\python.exe") (Join-Path $hub "tools\hubctl.py") restart
```

```bash
hub="$HOME/.local-ai-hub"
"$hub/.venv/bin/python" "$hub/tools/hubctl.py" restart
```

For rollback, run the `tools/rollback_snapshot.py create` and `restore` commands above with the same labels/roots and `--service-stopped`. After restore, reconcile the same registration once with `tools/service.py install` from the restored tree. Windows:

```powershell
$hub = Join-Path $HOME ".local-ai-hub"
& (Join-Path $hub ".venv\Scripts\python.exe") (Join-Path $hub "tools\service.py") install
```

macOS/Linux:

```bash
hub="$HOME/.local-ai-hub"
"$hub/.venv/bin/python" "$hub/tools/service.py" install
```

Service registration is external to the file snapshot. If service installation reports `detached-fallback`, reboot-persistent service acceptance fails and requires operator review. Do not create a second service or daemon to make a failed gate pass.

| Gate | Required evidence | Pass condition |
|---|---|---|
| Clean host | Run one install command above per platform; inspect generated MCP entries and service manager. | One installation/config/state directory, one user service/supervisor, stdio proxies only; no per-agent/chat/worktree daemon. No `detached-fallback`. |
| Multi-chat/worktree | Connect at least two clients from separate worktrees under one OS account. Send explicit caller `root` through MCP API and `HubClient`. | Same daemon/service handles both; each root passes `security.allowed_roots`; effective tenants derive from principal plus canonical root. |
| Auth and isolation | Check loopback bind, token-protected routes, rootless principal scope, allowed/outside/missing/symlink roots, tenant metadata mismatch, and browser route tenant. | Remote/anonymous access rejected; empty `allowed_roots` denies root-scoped memory/task; tenant mismatch is terminal 403; labels cannot select another tenant. |
| Update | Update a clean canonical tree, rerun installer once, inspect config/state and agent MCP configs. | Same service identity is reconciled, unrelated agent entries survive, version/config/state match, no duplicate service or supervisor. |
| Restart and login | Run `hubctl.py restart`, then repeat status/health checks; log out/in or reboot on each host. | One service returns online; durable tasks/jobs/state reopen; in-memory conversations are documented as lost on restart; no duplicate daemon appears. |
| Rollback | Stop service; snapshot code/config/state and each managed MCP config; restore matching release with same roots; reconcile the existing service once. | Restored code/config/state/proxies match; service registration remains singular; no older code opens newer state. |

T03/T04/T13 integration and all platform gates remain unverified in this candidate. Do not treat this matrix as executed evidence.

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

Hot-query preprocessing already warms deterministic, index and RAG capsules while idle; it cannot safely pre-generate historical model answers because prompts/output are deliberately not persisted. Repository artifacts are keyed by canonical parameters and watcher-backed root revision, while semantic reuse stays scoped to matching context identity. Use `batch_delegate` for independent local-model work and let the client coalesce identical active HTTP requests. Serena disables itself for a process when its installation is proven incomplete; transient failures cool down only the affected root and fall back to built-in indexes. Repair the external Serena environment before the next hub restart instead of raising retry budgets.

SQLite-backed derived stores use short busy timeouts and bounded retries. A transient `locked`/`busy` result is treated as contention and degrades to a cache miss/write drop where safe; it is not treated as database corruption. If overload or another retryable response is returned, clients should back off rather than immediately duplicating the request.

Normal hub responses use HTTP/1.1 so clients may reuse loopback connections. Admission rejections intentionally close their socket and include both `Retry-After: 1` and JSON `retry_after_seconds: 1`; callers should wait rather than create retry storms.
 
## Agent Operating System operations
 
- State file: stored under `server.state_dir / agent_state.sqlite3`.
- Retention & cleanup: `agent_state_cleanup()` removes expired incidents, receipts, and unconfirmed memory candidates according to `retention_days` without removing active tasks.
- Controlled promotion: Promotion of memory to global scope or learning candidates to promoted status strictly requires explicit operator approval (`approver="user"`).
- Selective export: `export_bundle(agent_state_record_ids=[...])` validates that no unapproved global memory record or disallowed scope is exported, raising `BundleValidationError` on violation.
- Recovery: The event stream and SQLite state reopen on restart, replaying and validating snapshots.

## Rollback and durable-state recovery

Before an upgrade, stop the Hub service (the single per-user registration) and confirm no Hub process has state databases open. Copy the active installation, its `config.toml`, the complete configured `server.state_dir`, and every agent MCP config file that setup manages to one dated backup set. Those agent files contain the stdio proxy registrations and must match the daemon release. Keep SQLite database files together with any `-wal` and `-shm` files. The state directory contains durable tasks, verification receipts, async jobs, memory, leases, and other operational records; cache-only backups do not cover them. Record the platform service-manager identity and enabled state separately; service registration is external to this file snapshot and must not become a per-agent/worktree service.

Create and verify a complete matched snapshot with `tools/rollback_snapshot.py` while the service is stopped. Give each non-overlapping source a stable label, and use the same labels and paths when restoring. Pass `--covers code config state` only after confirming the selected roots jointly contain the active installation, `config.toml`, and complete `server.state_dir`. Add each separately stored managed agent MCP config as another `--root` (for example `agent-codex`); do not add those labels to `--covers`, which tracks only the required Hub code/config/state set. If the configuration or state directory is inside the installation root, include it through that enclosing root and do not pass overlapping roots. Replace the example paths with the resolved paths for this Hub installation:

```powershell
python tools/rollback_snapshot.py create --output "D:\HubBackups\pre-upgrade-2026-09-28" `
  --root code="C:\Path\To\Hub" `
  --root config="C:\Path\To\config.toml" `
  --root state="C:\Path\To\state" `
  --root agent-codex="C:\Path\To\.codex\config.toml" `
  --covers code config state `
  --service-stopped
```

The command copies every selected root, writes a manifest, and verifies its SHA-256 digests. Keep the snapshot directory outside the source roots. Do not start the upgraded service until the snapshot command reports success.

If the upgraded service fails or reports an incompatible database schema, stop it and preserve its current state directory for investigation. Restore the previous installation, matching Hub configuration, matching state directory, and matching agent MCP config files from the same backup set. Reconcile the existing single user-service registration with the matching restored release before restarting it; never add a second registration for another agent, chat, or worktree. Do not run older code against state written by a newer release. Keep the backup until doctor checks and task/evidence lookups pass on the restored release.

Restore using the same root labels and resolved paths:

```powershell
python tools/rollback_snapshot.py restore --snapshot "D:\HubBackups\pre-upgrade-2026-09-28" `
  --root code="C:\Path\To\Hub" `
  --root config="C:\Path\To\config.toml" `
  --root state="C:\Path\To\state" `
  --root agent-codex="C:\Path\To\.codex\config.toml" `
  --covers code config state `
  --service-stopped
```

Restore verifies the snapshot before changing targets, stages each root before replacing it, and preserves the pre-rollback files beside their original paths with a `.pre-rollback-<id>` suffix. Keep those copies until recovery checks pass.

The installer does not create a Hub code/configuration/state rollback snapshot. Confirm the dated backup exists before upgrade. If no matching state backup exists, preserve the current database files and logs; do not delete them or start an older release against them.
