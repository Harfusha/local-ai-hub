# Native desktop migration — evidence and parity register

Status: **partial implementation; not a replacement release**. This is the
requested feature/verification matrix, not a second project plan. The repository
plan tool was unavailable in this environment; no plan files were modified.

## Architecture

Use Python 3.11+ and Tcl/Tk (tkinter/ttk), initially from the source checkout:
`python tools/desktop.py [--config /path/to/config.toml]`. This adds no pip
runtime dependency and does not use HTTP-served HTML, Electron, or a browser.
Tcl/Tk must be present in the Python installation (some Linux distributions
package it separately). The suitability for rich charts, very large lists,
accessibility, and distribution remains to be verified on real desktops.

The desktop is a separate process. Its health probe and read operations use
the existing loopback HubClient with auto_start=False; only explicit Start
invokes the lifecycle CLI. Stop/restart use the existing supervisor-aware CLI
and do not introduce a second service manager. The desktop has no arbitrary
command runner. Maintenance uses fixed route/payload pairs and confirmations.
Workers serialize operations outside the GUI event loop; no view polling or
parallel expensive reads are started in the background. Status is probed every
five seconds. Rendered text has a 250,000-character display cap (not API
pagination or virtualization). Closing the window does not request service stop.

## Page-level parity matrix

"Partial" means a real implementation exists but not all fields, actions or
error semantics of the browser UI are covered. No row is runtime-verified yet.

| Dashboard page / workflow | Desktop location | Current coverage | Acceptance verification still required |
|---|---|---|---|
| Overview: live workload, health, metrics, hotspots | Overview, Hardware | Partial: endpoint snapshots, no charts or workload drilldown | Compare cards, periods, health/warming/stale states and workload drilldowns |
| Requests: scheduler, active API, async jobs, work orders, history | Future Requests | Missing dedicated screen | Compare filtering/paging, cancellation, retry, trace links, job failures |
| Tasks: contracts, tasks, memory, incidents, run history, trace inspector, vision review, endpoint analytics | Tasks, Memory, Incidents | Partial scoped lists; no mutations, runs, traces, modals, analytics | Create/complete/fail tasks with receipt gate, memory and incident forms, trajectories, trace and vision review |
| Coordination: plans, board, dependencies, locks, semaphore | File leases | Partial lease read only | Scope isolation, revision conflict, board editing, semaphores, worktree release, lease owner checks |
| Projects & preprocessing | Projects | Partial status read only | Register, configure, remove, pause, resume, progress and unavailable indexes |
| Commands | Future Commands | Missing dedicated screen | Running/blocked command drilldown, approved broker actions, worktrees; never bypass policy |
| Models & search | Search workspaces, Hardware, Overview | Partial snapshots | Model compare, runtime inventory, statistics, profiles, cache, agents, route/token/latency metrics, evals, benchmarks, Laya, embedding/rerank, optimization |
| Service health | Service health, Diagnostics, toolbar | Partial log tail/doctor + start/stop/restart | Counters, fingerprints, circuits, crash journal, process history, export/password, log search/copy, actual service lifecycle |
| Settings | Settings — activity mode, toolbar | Partial activity mode only | Typed full config forms, validation, redaction, persistence, reset/restart-required and partial failures |
| Transfers | Future Transfers | Missing | Export/import ZIP, scope, password, integrity, failure and cancellation |
| Activity | Activity | Partial bounded event snapshot | Cursor, filters, SSE, pause, stale/reconnect and detail modals |
| Global control menu | Toolbar / maintenance selector | Partial: mode, DB optimization, expired cache, stale agent cleanup | Detailed telemetry consent and purge, stats purge, preprocessing pause/resume, diagnostic results and failure states |
| Service unavailable | Toolbar | Explicit Start and unreachable state; no implicit autostart | Cold start, supervisor already warming, permission failure, timeout, restart failure, close during transition |
| Desktop and service independence | Window close | No stop on close; busy close blocked | Start/stop via CLI, externally stopped Hub, desktop relaunch, concurrent operations |
| Web UI cutover | Not performed | Blocked by incomplete parity | Remove static routes/assets and references, preserve HTTP API/MCP, verify old routes no longer serve UI |

## CLI entrypoint inventory

The following commands were extracted from the current `tools/hubctl.py` argparse
registry. Subcommands/flags still need full contract inventory. All existing
commands are retained. The "candidate" column identifies the current desktop
surface or the required future surface, not a completed implementation.

| CLI command | Candidate desktop surface | Verification / status |
|---|---|---|
| `status` | Toolbar + Overview | Controller present; run focused tests and real CLI/API integration |
| `start` | Start Hub | Controller present; run focused tests and real CLI/API integration |
| `stop` | Stop Hub | Controller present; run focused tests and real CLI/API integration |
| `restart` | Restart Hub | Controller present; run focused tests and real CLI/API integration |
| `watch` | Future typed operational form or documented CLI-only workflow | Incomplete; classify subcommands/options and test parity or document exclusion |
| `dashboard` | Retained pending cutover | Incomplete; classify subcommands/options and test parity or document exclusion |
| `service-status` | Future typed operational form or documented CLI-only workflow | Incomplete; classify subcommands/options and test parity or document exclusion |
| `agent-state` | Scoped Tasks/Memory/Incidents reads only | Incomplete; classify subcommands/options and test parity or document exclusion |
| `cleanup` | Confirmed stale agent state cleanup only | Incomplete; classify subcommands/options and test parity or document exclusion |
| `clean` | Future typed operational form or documented CLI-only workflow | Incomplete; classify subcommands/options and test parity or document exclusion |
| `generate` | Future typed operational form or documented CLI-only workflow | Incomplete; classify subcommands/options and test parity or document exclusion |
| `tasks` | Scoped Tasks read only | Incomplete; classify subcommands/options and test parity or document exclusion |
| `plans` | Future typed operational form or documented CLI-only workflow | Incomplete; classify subcommands/options and test parity or document exclusion |
| `memory` | Scoped Memory read only | Incomplete; classify subcommands/options and test parity or document exclusion |
| `doctor` | Diagnostics | Controller present; run focused tests and real CLI/API integration |
| `logs` | Service health log tail | Controller present; run focused tests and real CLI/API integration |
| `pause` | Activity mode selector only; alias semantics not verified | Incomplete; classify subcommands/options and test parity or document exclusion |
| `resume` | Activity mode selector only; alias semantics not verified | Incomplete; classify subcommands/options and test parity or document exclusion |
| `mode` | Activity mode selector | Controller present; run focused tests and real CLI/API integration |
| `caveman-compress` | Future typed operational form or documented CLI-only workflow | Incomplete; classify subcommands/options and test parity or document exclusion |
| `compress-instructions` | Future typed operational form or documented CLI-only workflow | Incomplete; classify subcommands/options and test parity or document exclusion |
| `client` | Future typed operational form or documented CLI-only workflow | Incomplete; classify subcommands/options and test parity or document exclusion |
| `knowledge` | Future typed operational form or documented CLI-only workflow | Incomplete; classify subcommands/options and test parity or document exclusion |

## Static dashboard control inventory

Extracted from literal button markup in `dashboard.html`. Each listed control
requires a native counterpart and a behavior/error regression test. Where the
page-level matrix lists partial coverage, only the named native operations
are present. Dynamic controls/templates and TypeScript modules must be
reconciled separately before declaring the inventory exhaustive.

| Existing control ID | Label | Verification |
|---|---|---|
| `detailedTelemetryToggle` | Detailed telemetry: Off | Reconcile native control; test handler, cancellation/confirmation and error |
| `purgeDebugTracesBtn` | Purge detailed traces | Reconcile native control; test handler, cancellation/confirmation and error |
| `optDbBtn` | Optimize databases | Reconcile native control; test handler, cancellation/confirmation and error |
| `doctorBtn` | Run diagnostics | Reconcile native control; test handler, cancellation/confirmation and error |
| `pauseEvents` | Pause live events | Reconcile native control; test handler, cancellation/confirmation and error |
| `activityModeActive` | Active | Reconcile native control; test handler, cancellation/confirmation and error |
| `activityModeGaming` | Gaming | Reconcile native control; test handler, cancellation/confirmation and error |
| `activityModeMaintenance` | Maintenance | Reconcile native control; test handler, cancellation/confirmation and error |
| `activityModePreprocessing` | Preprocessing | Reconcile native control; test handler, cancellation/confirmation and error |
| `prepToggle` | Pause preprocessing | Reconcile native control; test handler, cancellation/confirmation and error |
| `purgeCacheBtn` | Purge expired cache | Reconcile native control; test handler, cancellation/confirmation and error |
| `purgeStatsBtn` | Purge all statistics | Reconcile native control; test handler, cancellation/confirmation and error |
| `overviewHealthAction` | Open details | Reconcile native control; test handler, cancellation/confirmation and error |
| `requestHistoryReset` | Reset | Reconcile native control; test handler, cancellation/confirmation and error |
| `agentOsRefresh` | ↻ Refresh | Reconcile native control; test handler, cancellation/confirmation and error |
| `agentOsCleanup` | 🧹 Cleanup stale state | Reconcile native control; test handler, cancellation/confirmation and error |
| `subtabTasks` | Tasks &amp; Contracts | Reconcile native control; test handler, cancellation/confirmation and error |
| `subtabMemory` | Memory &amp; Facts | Reconcile native control; test handler, cancellation/confirmation and error |
| `subtabIncidents` | Incidents &amp; lessons | Reconcile native control; test handler, cancellation/confirmation and error |
| `subtabTrajectories` | Run history | Reconcile native control; test handler, cancellation/confirmation and error |
| `subtabEndpointStatsJump` | 📊 Endpoint &amp; MCP Analytics ↓ | Reconcile native control; test handler, cancellation/confirmation and error |
| `agentOsCreateTaskBtn` | + Create Task | Reconcile native control; test handler, cancellation/confirmation and error |
| `agentOsTasksMore` | Load next tasks | Reconcile native control; test handler, cancellation/confirmation and error |
| `agentOsRecordMemBtn` | + Record Memory | Reconcile native control; test handler, cancellation/confirmation and error |
| `agentOsRecordIncBtn` | + Record incident | Reconcile native control; test handler, cancellation/confirmation and error |
| `trajRefreshBtn` | ↻ Refresh Run History | Reconcile native control; test handler, cancellation/confirmation and error |
| `visionReviewOpen` | Frontend vision review | Reconcile native control; test handler, cancellation/confirmation and error |
| `traceRefresh` | Refresh | Reconcile native control; test handler, cancellation/confirmation and error |
| `epStatsRefreshBtn` | ↻ Obnovit | Reconcile native control; test handler, cancellation/confirmation and error |
| `epStatsResetBtn` | Resetovat | Reconcile native control; test handler, cancellation/confirmation and error |
| `epScopeActive` | Aktivní (0) | Reconcile native control; test handler, cancellation/confirmation and error |
| `epScopeAll` | Všechny (0) | Reconcile native control; test handler, cancellation/confirmation and error |
| `epScopeUnused` | Nepoužité (0) | Reconcile native control; test handler, cancellation/confirmation and error |
| `subtabCoordBoard` | Project Board (Kanban) | Reconcile native control; test handler, cancellation/confirmation and error |
| `subtabCoordSemaphores` | Resource Semaphores | Reconcile native control; test handler, cancellation/confirmation and error |
| `subtabCoordPlanProgress` | Plan Progress | Reconcile native control; test handler, cancellation/confirmation and error |
| `subtabCoordBriefing` | Session Briefing | Reconcile native control; test handler, cancellation/confirmation and error |
| `coordNewPlanBtn` | + New Plan | Reconcile native control; test handler, cancellation/confirmation and error |
| `coordEditPlanBtn` | Edit Plan | Reconcile native control; test handler, cancellation/confirmation and error |
| `coordNewCardBtn` | + Add Task | Reconcile native control; test handler, cancellation/confirmation and error |
| `coordRefreshBoardBtn` | ↻ Refresh Board | Reconcile native control; test handler, cancellation/confirmation and error |
| `coordCompactBtn` | ▤ Compact (On) | Reconcile native control; test handler, cancellation/confirmation and error |
| `coordAcquireSemBtn` | + Acquire Semaphore | Reconcile native control; test handler, cancellation/confirmation and error |
| `coordRefreshSemBtn` | ↻ Refresh | Reconcile native control; test handler, cancellation/confirmation and error |
| `coordRefreshPlanProgressBtn` | ↻ Refresh | Reconcile native control; test handler, cancellation/confirmation and error |
| `coordGenerateBriefingBtn` | ⚡ Generate Session Briefing | Reconcile native control; test handler, cancellation/confirmation and error |
| `prepAllToggle` | Pause all projects | Reconcile native control; test handler, cancellation/confirmation and error |
| `regProjectBtn` | + Register | Reconcile native control; test handler, cancellation/confirmation and error |
| `cleanMissingBtn` | 🧹 Clean missing | Reconcile native control; test handler, cancellation/confirmation and error |
| `refreshWorktreesBtn` | ↻ Refresh Worktrees | Reconcile native control; test handler, cancellation/confirmation and error |
| `pruneWorktreesBtn` | 🧹 Prune Stale Worktrees | Reconcile native control; test handler, cancellation/confirmation and error |
| `residentInventoryRefresh` | Refresh resident inventory | Reconcile native control; test handler, cancellation/confirmation and error |
| `diagramVisionReviewOpen` | Review raster with vision | Reconcile native control; test handler, cancellation/confirmation and error |
| `ragWorkspaceReviewBtn` | Review indexes | Reconcile native control; test handler, cancellation/confirmation and error |
| `arenaRunBtn` | Run comparison | Reconcile native control; test handler, cancellation/confirmation and error |
| `reliabilityAction` | Open request history | Reconcile native control; test handler, cancellation/confirmation and error |
| `diagnosticsExportBtn` | Download full support ZIP | Reconcile native control; test handler, cancellation/confirmation and error |
| `diagnosticsCopyPassword` | Copy password | Reconcile native control; test handler, cancellation/confirmation and error |
| `diagnosticsClosePassword` | Close | Reconcile native control; test handler, cancellation/confirmation and error |
| `loadLogs` | Refresh | Reconcile native control; test handler, cancellation/confirmation and error |
| `copyLogsBtn` | Copy | Reconcile native control; test handler, cancellation/confirmation and error |
| `cfgSave` | Save overrides (restart required) | Reconcile native control; test handler, cancellation/confirmation and error |
| `cfgReload` | Reload view | Reconcile native control; test handler, cancellation/confirmation and error |
| `cfgReset` | Reset dashboard overrides | Reconcile native control; test handler, cancellation/confirmation and error |
| `bundleImport` | Import selected ZIP | Reconcile native control; test handler, cancellation/confirmation and error |
| `modalClose` | Close | Reconcile native control; test handler, cancellation/confirmation and error |
| `visionReviewClose` | Close | Reconcile native control; test handler, cancellation/confirmation and error |
| `visionCaptureCurrentTab` | Capture current tab | Reconcile native control; test handler, cancellation/confirmation and error |
| `visionReviewSubmit` | Run vision review | Reconcile native control; test handler, cancellation/confirmation and error |
| `taskCriteriaRefresh` | Refresh status | Reconcile native control; test handler, cancellation/confirmation and error |
| `trajEventPager` | ${trajectoryPageError?'Retry page':'Load next events'} | Reconcile native control; test handler, cancellation/confirmation and error |
| `confirmDeleteProjectBtn` | Confirm Unregister / Purge | Reconcile native control; test handler, cancellation/confirmation and error |
| `confirmCleanMissingBtn` | 🧹 Prune Missing Projects | Reconcile native control; test handler, cancellation/confirmation and error |
| `confirmConfigReset` | Reset overrides | Reconcile native control; test handler, cancellation/confirmation and error |
| `confirmControlAction` | ${esc(details.title)} | Reconcile native control; test handler, cancellation/confirmation and error |
| `workReset` | Reset | Reconcile native control; test handler, cancellation/confirmation and error |
| `traceTableReset` | Reset | Reconcile native control; test handler, cancellation/confirmation and error |

Inline handler names found in HTML (including generated templates):
`$`, `checkTaskCompletionGate`, `completeTaskAction`, `confirmCleanMissing`, `confirmDeleteProject`, `copyText`, `deleteMemoryAction`, `deletePlanTask`, `deleteProjectDialog`, `editPlanTask`, `executeCleanupAction`, `exportBundle`, `openDoctorModal`, `openTaskById`, `openTrace`, `pollStatus`, `projectAction`, `quickAcquireSem`, `releaseLeaseAction`, `releaseSemaphore`, `requestFrontendVisionRepair`, `setEpTableSort`, `setPreprocessing`, `showFailTaskInput`, `submitFailTask`, `toggleCardCompact`, `transitionTaskAction`.

## Literal API references in dashboard HTML

The desktop currently consumes only the fixed routes in `VIEWS` and
`MAINTENANCE` in `tools/desktop.py`; other API routes must be inventoried
with their schemas, auth, scope, payload, responses, binary/SSE contracts and
callers. Preserve the backend routes unless proven presentation-only.
This list is lexical, not a complete route registry.

- `/api/admin/mode`
- `/api/agent-state/`
- `/api/agent-state/cleanup`
- `/api/agent-state/events`
- `/api/agent-state/incidents`
- `/api/agent-state/memory`
- `/api/agent-state/tasks`
- `/api/agent-state/verification`
- `/api/bundle/export`
- `/api/bundle/import`
- `/api/command`
- `/api/config`
- `/api/config/update`
- `/api/coord/plan_board_view`
- `/api/coord/plan_create`
- `/api/coord/plan_get`
- `/api/coord/plan_list`
- `/api/coord/plan_task_delete`
- `/api/coord/plan_task_edit`
- `/api/coord/plan_update`
- `/api/coord/semaphore_acquire`
- `/api/coord/semaphore_release`
- `/api/coord/semaphore_status`
- `/api/coord/session_briefing`
- `/api/coord/worktree_prune`
- `/api/coord/worktree_release`
- `/api/coord/worktrees`
- `/api/debug-traces`
- `/api/debug-traces/`
- `/api/debug-traces/purge`
- `/api/delegate`
- `/api/diagnostics/export`
- `/api/doctor`
- `/api/hardware/system`
- `/api/leases`
- `/api/leases/release`
- `/api/live`
- `/api/live/status`
- `/api/logs/tail`
- `/api/maintenance/optimize_db`
- `/api/maintenance/purge_cache`
- `/api/mode`
- `/api/preprocess`
- `/api/preprocess/status`
- `/api/project/config`
- `/api/rag/workspaces`
- `/api/telemetry/endpoint-stats`
- `/api/telemetry/endpoint-stats/reset`
- `/api/vision/review`

## Verification

Added `tests/test_desktop_control.py`: offline reads, explicit repository
scope and encoding, start/stop/restart delegation, idempotent start,
allowlist rejection, argv/no-shell transport, API failure and maintenance
confirmation at the response boundary. Tests are not executed in this environment.

Required commands, from the actual checkout, per AGENTS.md:

```sh
python -m pytest tests/test_desktop_control.py -q
python -m pytest tests/test_test_environment_isolation.py -q
python -m compileall -q src tools tests
python tools/release_check.py
python tools/selftest.py
```

Then run targeted lifecycle, HTTP/MCP and desktop end-to-end tests after
identifying the existing test modules. No full unbounded pytest run.

Performance measurement: not run. The environment has no repository
checkout (DNS failure to GitHub) or interactive target desktop/service.
On Windows and Linux, measure cold/warm first-window and first-ready latency
using monotonic timestamps, and record desktop process RSS/private memory and
CPU delta over a 60-second idle sample with Hub stopped and running. Measure
service and desktop independently; repeat at least three times and report
actual results plus hardware/OS/Python/Tk versions. No threshold claimed.

## Remaining acceptance gates

- Full parity against HTML, dashboard TypeScript and Python/HTTP routes and CLI
  registries, including dynamically rendered controls.
- Native typed screens, forms, action-specific errors, paging, searches, charts,
  cancellation, config and transfer handling, packaging/launchers.
- Verify authentication and scope with real configured clients, API/MCP
  compatibility, offline/online lifecycle, accessibility, and resource usage.
- Remove web UI only after parity and tests pass; keep API and MCP. The draft
  branch deliberately retains it to avoid breaking existing clients.
