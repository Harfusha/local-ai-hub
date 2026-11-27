# Native desktop migration — evidence and parity register

Status: **draft cutover; runtime web UI disconnected, legacy frontend sources and build removed; full desktop parity and verification incomplete. Do not merge as a replacement release.** This is the
requested feature/verification matrix, not a second project plan. The repository
plan tool was unavailable in this environment; no plan files were modified.

## Architecture (Rust revision)

The desktop is now compiled Rust, using eframe/egui 0.31.1 with the Glow
OpenGL renderer. No Tkinter, Qt, Electron, browser engine or local UI server.
The toolkit is MIT/Apache-2.0 licensed. The explicit 0.31.1 pin targets a
known App::update API, not a claim to be the newest release. Upgrade and
dependency license/security review remain release gates.

Build from a trusted Hub checkout with Rust stable and platform OpenGL
libraries: `cargo build --manifest-path desktop/Cargo.toml --release`.
Run `python tools/hubctl.py desktop` (the legacy `dashboard` CLI alias opens the same native binary), or run `desktop/target/release/local-ai-hub-desktop` directly from the Hub root. Set LOCAL_AI_HUB_ROOT, LOCAL_AI_DESKTOP_PYTHON,
LOCAL_AI_CONFIG or choose the installation in the UI. Python is still
required by the existing Hub; it is not used for GUI rendering. The desktop
executes a fixed adapter script with JSON stdin/stdout and named operations.
No arbitrary route, shell or command broker is exposed. Each operation uses
a short-lived adapter process; it delegates to HubClient(auto_start=False)
or the existing lifecycle CLI. There is no resident Python GUI or bridge
while idle. No new network listener or secret storage is introduced.

One operation runs in a worker thread; the renderer is event-driven apart
from a 30-second focused-window health probe, which can be disabled. Views
load explicitly. The searchable response inspector virtualizes visible
rows, caps at 12,000 flattened fields and 8 MB adapter response, and exposes
individual detail/copy. Native schema-specific tables, record details and a Kanban with separate declared/verified progress are implemented, alongside bounded trace pages and revision-aware actions. Basic request duration chart, scoped paging and bounded SSE follow are implemented. Specialized charts, full history paging and action-specific presentations remain incomplete. The service
lifecycle and desktop lifecycle remain separate. Closing during operations
is blocked to avoid interrupting a mutation.

CI: .github/workflows/desktop.yml builds and runs Rust tests on Ubuntu 22.04, Windows and macOS, runs focused bridge/HTTP/packaging tests, and measures first window and 60 seconds of idle RSS/CPU under Linux Xvfb/software OpenGL with Hub absent. Linux baseline was pinned after a real CI artifact required GLIBC_2.43 and could not launch on the available older runtime. Native binaries
are unsigned portable builds. Cargo.lock is committed from a successful CI resolution (390 packages); CI uses --locked. Stable release publication requires native verification and validated four-platform ZIP receipts. Versioned binary installation is integrated into setup/update, with persistent headless opt-out. Full runtime portability, GPU/driver behavior and resource consumption remain unverified.

## Page-level parity matrix

"Partial" means a real implementation exists but not all fields, actions or
error semantics of the browser UI are covered. No row is runtime-verified yet.

| Dashboard page / workflow | Desktop location | Current coverage | Acceptance verification still required |
|---|---|---|---|
| Overview: live workload, health, metrics, hotspots | Overview, Hardware | Partial: endpoint snapshots, recent request duration chart, health and project progress; no full workload drilldown | Compare cards, periods, health/warming/stale states and workload drilldowns |
| Requests: scheduler, active API, async jobs, work orders, history | Requests, Trace index | Partial native recent-request and trace tables, before/after event paging, metrics, opt-in stored content paging and redacted trace export, endpoint analytics | Compare filtering/paging, cancellation, retry, trace links, job failures |
| Tasks: contracts, tasks, memory, incidents, run history, trace inspector, vision review, endpoint analytics | Tasks, Memory, Incidents | Partial scoped lists, create/get/complete/fail/transition, verification completion gate, run history with retention gaps, repository fact record/delete, incident record, bounded trace event pages | Create/complete/fail tasks with receipt gate, memory and incident forms, trajectories, trace and vision review |
| Coordination: plans, board, dependencies, locks, semaphore | Plans, Plan board, Semaphores, File leases, Worktrees | Partial native Kanban and verified progress, plan create/update and task edit/delete with expected revision, semaphore/lease/worktree actions and briefing | Scope isolation, revision conflict, board editing, semaphores, worktree release, lease owner checks |
| Projects & preprocessing | Projects | Partial status and project config reads, register/reindex/pause/resume/unregister with explicit purge option and global controls | Register, configure, remove, pause, resume, progress and unavailable indexes |
| Commands | Commands, Worktrees | Partial running command table, counters, blocked-reason breakdown, record detail and scoped worktree actions; no broker execution form | Running/blocked command drilldown, approved broker actions, worktrees; never bypass policy |
| Models & search | Search workspaces, Hardware, Overview | Partial snapshots, model inventory, benchmark and telemetry report, two-route comparison | Model compare, runtime inventory, statistics, profiles, cache, agents, route/token/latency metrics, evals, benchmarks, Laya, embedding/rerank, optimization |
| Service health | Service health, Diagnostics, toolbar | Partial log tail/doctor + start/stop/restart, process-session and error tables, encrypted diagnostics export in Transfers | Counters, fingerprints, circuits, crash journal, process history, export/password, log search/copy, actual service lifecycle |
| Settings | Settings — activity mode, toolbar | Partial typed configuration draft from server values, batch-save changed overrides, activity mode, separate live telemetry mode, override reset | Typed full config forms, validation, redaction, persistence, reset/restart-required and partial failures |
| Transfers | Transfers | Partial bounded ZIP export/import and encrypted diagnostics export with returned password | Export/import ZIP, scope, password, integrity, failure and cancellation |
| Activity | Activity | Partial bounded event snapshot and focus-only SSE follow with cursor/deduplication | Cursor, filters, SSE, pause, stale/reconnect and detail modals |
| Global control menu | Toolbar / maintenance selector | Partial: mode, DB optimization, expired cache, stale agent cleanup, detailed telemetry toggle/purge, stats purge, global preprocessing | Detailed telemetry consent and purge, stats purge, preprocessing pause/resume, diagnostic results and failure states |
| Service unavailable | Toolbar | Explicit Start and unreachable state; no implicit autostart | Cold start, supervisor already warming, permission failure, timeout, restart failure, close during transition |
| Desktop and service independence | Window close | No stop on close; busy close blocked | Start/stop via CLI, externally stopped Hub, desktop relaunch, concurrent operations |
| Web UI cutover | HTTP server, packaging, CLI | Runtime disconnected in draft: old GET paths return JSON 404, UI mixin removed, package data excludes static assets, CLI launches desktop. HTML/TypeScript, frontend build and DOM-only tests deleted; no served fallback | Complete equivalent native regression coverage; verify clean package and API/MCP compatibility |

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
| `watch` | Focus-only health and event polling; terminal watch remains CLI-only | Implemented surface (not all flags); real integration and acceptance pending |
| `desktop` / legacy `dashboard` | Native launcher | No HTTP URL; verify launch and missing binary error |
| `service-status` | Operator tools: supervisor status | Implemented surface (not all flags); real integration and acceptance pending |
| `agent-state` | Tasks/Memory/Incidents plus storage inventory | Implemented surface (not all flags); real integration and acceptance pending |
| `cleanup` | Maintenance and Operator tools: cleanup, ports, offline database optimization | Implemented surface (not all flags); real integration and acceptance pending |
| `clean` | Operator tools: clean build/cache files | Implemented surface (not all flags); real integration and acceptance pending |
| `generate` | Operator tools: generate/deploy agent artifacts | Implemented surface (not all flags); real integration and acceptance pending |
| `tasks` | Scoped paged Tasks with mutations | Implemented surface (not all flags); real integration and acceptance pending |
| `plans` | Plans / Plan board with revision-aware actions | Implemented surface (not all flags); real integration and acceptance pending |
| `memory` | Scoped Memory list/record/delete | Implemented surface (not all flags); real integration and acceptance pending |
| `doctor` | Diagnostics | Controller present; run focused tests and real CLI/API integration |
| `logs` | Service health log tail | Controller present; run focused tests and real CLI/API integration |
| `pause` | Activity mode selector; explicit confirmation | Implemented surface (not all flags); real integration and acceptance pending |
| `resume` | Activity mode selector; explicit confirmation | Implemented surface (not all flags); real integration and acceptance pending |
| `mode` | Activity mode selector | Controller present; run focused tests and real CLI/API integration |
| `caveman-compress` | Operator tools: stage candidates; in-place apply CLI-only (review binding missing) | Implemented surface (not all flags); real integration and acceptance pending |
| `compress-instructions` | Operator tools: stage candidates; in-place apply CLI-only | Implemented surface (not all flags); real integration and acceptance pending |
| `client` | Operator tools: status/detect/preview/inject/remove/config | Implemented surface (not all flags); real integration and acceptance pending |
| `knowledge` | Operator tools: typed catalog, query, audit, validation, mutations, batches, migration and handoff | Implemented surface (not all flags); real integration and acceptance pending |

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

The desktop consumes only fixed/named operations in `VIEWS`,
`MAINTENANCE`, `dispatch` and `transfer` in `tools/desktop.py`; other API routes must be inventoried
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

Added `desktop/src/main.rs` unit tests for bounded rows, paths and named IPC
requests, and `tests/test_desktop_control.py`: offline reads, explicit repository
scope and encoding, start/stop/restart delegation, idempotent start,
allowlist rejection, argv/no-shell transport, API failure and maintenance
confirmation at the response boundary. Earlier Rust/bridge CI succeeded on revisions 15ddb42 and a2c30d2; current revision after cutover and native table changes is not verified. Local direct Git checkout still fails DNS; no local Cargo. Linux artifact from a2c30d2 was downloaded and checked with ldd: GLIBC_2.43 required and unavailable locally. New pinned Linux build/smoke test is pending.

Required commands, from the actual checkout, per AGENTS.md:

```sh
cargo test --manifest-path desktop/Cargo.toml
cargo build --manifest-path desktop/Cargo.toml --release
python -m pytest tests/test_desktop_control.py -q
python -m pytest tests/test_test_environment_isolation.py -q
python -m compileall -q src tools tests
python tools/release_check.py
python tools/selftest.py
```

Then run targeted lifecycle, HTTP/MCP and desktop end-to-end tests after
identifying the existing test modules. No full unbounded pytest run.

Performance measurement: not yet available. The first actual Linux artifact failed loader compatibility before window creation; the pinned CI baseline and Xvfb smoke script address this failure and collect real measurements. The environment has no repository
checkout (DNS failure to GitHub) or interactive target desktop/service.
On Windows and Linux, measure cold/warm first-window and first-ready latency
using monotonic timestamps, and record desktop process RSS/private memory and
CPU delta over a 60-second idle sample with Hub stopped and running. Measure
service and desktop independently; repeat at least three times and report
actual results plus hardware/OS/Rust/eframe/Python versions. No threshold claimed.

## Remaining acceptance gates

- Full parity against HTML, dashboard TypeScript and Python/HTTP routes and CLI
  registries, including dynamically rendered controls.
- Complete native typed screens, remaining forms, action-specific errors, paging, searches, charts,
  cancellation, config and transfer handling, packaging/launchers.
- Verify authentication and scope with real configured clients, API/MCP
  compatibility, offline/online lifecycle, accessibility, and resource usage.
- Complete physical removal of legacy HTML/TypeScript/build/test references only after equivalent native behavior tests exist. Draft HTTP cutover already disables the routes and excludes assets from packaging; keep PR draft until full parity and verification. Preserve HTTP API/MCP.

## Current cutover blockers

- Legacy dashboard sources and frontend build references were physically deleted; DOM-only tests were retired and mixed tests migrated to preserve backend assertions. Native behavior coverage is not yet equivalent to the historical browser suite. The old implementation and tests remain available in Git history.
- Update controls, detailed vision review, complete settings/editor flows, live event streaming, trace/history linking, advanced command/agent controls, and full packaging are not complete. Existing backend endpoints remain intact; do not weaken auth or remove backend tests to force a green suite.
- Current head has not passed the full targeted CI after these changes; no full service lifecycle, API/MCP regression, or actual cross-platform runtime verification is available. Draft must not be merged as finished.

## Latest implementation evidence

- The branch was synchronized with master at `f8e8524` (merge `7dfa7fc`).
- The runtime cutover removes browser routes and the source cutover removes HTML/TypeScript and the frontend compiler. The AST cutover check exposed thirteen additional stale test imports; these were migrated in `747a34f`. Do not interpret this source migration as a passing test run.
- Native controls now include task paging, vision PNG/JPEG review, scoped SSE, typed settings, explicit local update confirmation, revision-aware plan actions, asynchronous work status/results/cancellation, memory/task enums, portable ZIP packaging and SHA-256-verified atomic binary installation.
- Previous native workflows succeeded at `15ddb42` and `a2c30d2` before the latest changes. Current head requires fresh full CI, Linux startup/idle metrics, Windows/macOS runtime acceptance, parity review and Cargo.lock. No verified completion claim.


## Implementation evidence, 2026-11-27

- CI-generated lockfile committed (`f016c71`); macOS build and bridge checks passed on `f74beef`. Earlier revision `9f186ee` passed Rust tests and builds on Windows/macOS and the Linux build, but the Linux runtime smoke failed. Xvfb diagnostics and dependencies were corrected; latest runtime and resource evidence remains pending.
- Operator catalog (`d205aa6`), release integration (`f93b19a`), trace/command/session UI (`b956d57`), and confirmation/headless hardening (`30ab53c`) are implementation evidence, not acceptance receipts.
- `master` was merged through `7c42227`. Existing master CI failures were confirmed independently; the invalid linter config, optional serializer typing, and selected stale fixtures were corrected without disabling the tests. Full CI and parity remain required before merge.


## Follow-up implementation and evidence (2026-11-27)

- Added scoped task run history, nonterminal task transitions and server completion receipts, explicit endpoint resets, project purge confirmation, observed-value settings drafts and changed-field batch saves.
- Added request filtering, scheduler queued/running records, recovery journal, trace server-side filters and bounded paging, token efficiency and circuit breaker summaries. Trace-index and run-event search use sanitized data.
- On 96a66b3, 264 focused Python tests passed. The new real HTTP/subprocess acceptance test subsequently failed on an incorrect positional assumption about unused endpoint rows; assertions now identify the exact recorded endpoint and check both roots before and after reset. Re-run required.
- A syntax error in the analytics column list was corrected in 9fbd6ed. Linux X11 runtime dependency correction is present; latest native matrix and resource measurements remain unverified.
- Parallel branch updates were preserved with expected-head leases. Full behavioral parity, lifecycle and installer acceptance, and release readiness remain gates; the PR stays draft.


## Latest native verification and follow-up

At `48c5722`, the [Native desktop workflow](https://github.com/Harfusha/local-ai-hub/actions/runs/45952403859) completed successfully across Windows, Linux, macOS ARM64 and macOS Intel. The bridge job passed 265 Python tests; Linux passed 21 Rust tests and the actual first-window/60-second idle runtime smoke under Xvfb with Hub absent. Reported first window: 0.310441 s; mean and peak RSS: 110,366,720 bytes (105.3 MiB); measured idle CPU: 0.0% of one core. This is one CI environment, not a hardware-independent performance guarantee or proof of online-service idle behavior. The main [CI workflow](https://github.com/Harfusha/local-ai-hub/actions/runs/45952403867) failed; scheduled integration runs on Windows 3.11/3.14 and Ubuntu 3.14 failed at collection because torch/Pillow were missing, while the platform cohort and critical coverage have other unresolved failures. Integration matrix entries marked successful but not scheduled are not passing full-suite evidence.

- `061ad1a`: repository/installation changes invalidate scoped selections, pending confirmations, continuation cursors and retained responses; navigation and repository edits are disabled during confirmation or installation selection.
- `4f5bd44`: explicit trace links from operational record details navigate to the existing bounded trace inspector. No request-ID-to-trace-ID guessing.
- `139b122`, `ca5c77e`, `46b223a`: dedicated native log-tail UI with 100/250/500-line selection, case-insensitive search, explicit clipboard copy, and a validated named bridge request. Python contract tests cover invalid limits, malformed responses, disabled diagnostics and no autostart. This restores the old log controls without serving HTML.
- These changes add targeted tests, not yet verified at the new head. Actual Windows/macOS window and lifecycle behavior, online idle resource measurements, comprehensive control parity, accessibility, main CI, and release acceptance remain incomplete. The local editing environment has no Cargo and cannot resolve github.com for a checkout; updates were made directly in this PR, not master or PR #11. Keep draft until evidence supports completion.


## Plan editing and main CI remediation

- [Native desktop at ec58849](https://github.com/Harfusha/local-ai-hub/actions/runs/45975426034) passed all four platform jobs and the bridge (277 Python tests). Linux ran 24 Rust tests and the Xvfb first-window/60-second idle smoke: 0.409865 s, mean RSS 110,592,000 bytes (105.47 MiB), 0.0% of one CPU core, Hub absent. This validates the previous scope/trace/log changes, not later edits.
- Main CI at ec58849 failed seven platform tests, two critical tests and three scheduled integration collections. The latter lacked Torch and Pillow. Unscheduled matrix rows are not full-suite receipts.
- Main CI changes: scheduler monitoring snapshots external state and cache metrics before locking its queue; real admission paths remain unchanged. Install CPU Torch/Pillow for scheduled integration suites rather than skipping their tests. Generated orchestrator test uses the actual generator; Antigravity current/legacy exact-hook recognition no longer aliases the same mutable configuration. Native-platform Devin paths and installed defaults are reflected in uninstall fixtures. MCP output contract failure retains a valid bounded correlation ID for diagnostic mode; budget/contract regressions exercise both configured diagnostic policies without changing the default projection.
- Plan and task editing now loads the complete canonical plan via the scoped `plan_get` operation. Drafts bind the exact plan ID, task ID and file revision and submit only changed fields, including criteria, next action, accountable role and blocker. Omitted and non-round-trippable criteria are preserved. Board cards are not full edit documents. Add-task uses a read preflight and the existing CAS revision, refuses existing IDs; no blind upsert resets a card. New bridge and Rust unit tests plus real HTTP/IPC plan isolation, stale revision and duplicate-ID acceptance scenarios cover these paths.
- New commits have not passed a final CI matrix; intermediate runs may be cancelled by newer pushes. The local environment still lacks Cargo and DNS resolution for a Git checkout. The active Hub planner is not available through this connection; no plan storage was edited. Full native parity, interactive Windows/macOS runtime and service lifecycle, online resource measurements, accessibility and signed installer/release acceptance remain incomplete. Do not treat this document or test additions as verification receipts. PR stays draft.


## Scoped operator workflows and follow-up verification

- At `06043c3`, [native CI](https://github.com/Harfusha/local-ai-hub/actions/runs/45979174741) passed the four Rust target jobs, including 26 Linux Rust tests and Linux Xvfb runtime smoke (first window 0.414 s, mean RSS 105.15 MiB, idle CPU 0.0% of one core, Hub absent). The bridge job passed 281 tests and failed one live plan fixture because its Git repositories had no HEAD. The [main workflow](https://github.com/Harfusha/local-ai-hub/actions/runs/45979174768) was superseded; its Linux Python 3.11 platform cohort recorded 584 passed, 13 skipped, two failed. These are not full green matrix receipts.
- Corrected real Git baseline setup, diagnostic correlation retention at the inner MCP contract boundary, and the standalone Antigravity uninstall fixture's explicit installation mode.
- Added bounded native telemetry timeline paging with cursor validation, correct POST doctor transport, typed diagnostic and timeline tables, and explicit project-to-configuration navigation. The historical project configuration view was read-only; no unsupported write endpoint was invented.
- Session briefing now uses the explicit repository root and allowed section names. The UI distinguishes bounded active-task previews and partial briefings. Memory search, creation and deletion use the selected scope and its exact identity; delete uses record ID instead of key. Unused memory text is not transmitted over IPC. Worktree memory deletion remains blocked by the server's verified-scope policy.
- File lease inventory is repository scoped. Release requires an exact observed owner and lease ID and checks positive released-row count; semaphore release requires the owner and actual release acknowledgment. Typed tables and selection use per-view identities rather than incidental trace/request IDs. Added regression tests for these transport and ownership contracts.
- These new commits require fresh CI. Actual online idle measurements, interactive Windows/macOS runtime and service lifecycle, accessibility, comprehensive historical control and CLI parity, and installer/release acceptance remain open. The PR remains draft. No local Cargo, GitHub checkout DNS or active Hub planner was available; no direct plan-store edits and no merge to master.
