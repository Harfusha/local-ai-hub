# Native desktop migration — evidence and parity register

Status: **draft cutover; runtime web UI disconnected, legacy frontend sources and build removed; full desktop parity and verification incomplete. Do not merge as a replacement release.** This is the
requested feature/verification matrix, not a second project plan. The authoritative
work plan is `.local-ai-hub/plans/plan_pr10_native_desktop.plan.json` and is
maintained through the Local AI Hub planner API.

## Current local audit — 2026-11-27

- `feat/native-desktop-hub` contains `origin/master` at `8fa0dbf3` via merge
  commit `eda8fca1`. Fetched `origin/feat/native-desktop-hub` at
  `5659dd0cfe2f67f30bcde6db4e249aa689ce9acb`; the remote and local commit
  match. Current uncommitted fixes are not pushed.
- Removed the obsolete `hubctl dashboard` alias and the launcher fallback to an
  unversioned `bin/local-ai-hub-desktop` binary. New installations use the
  versioned path; development builds use `desktop/target/release`.
- Versioned installation now requires an explicit version and performs a
  one-time cleanup of the retired unversioned executable after install.
- Focused desktop CLI/controller/installer checks: 192 passed. HTTP/IPC and
  service-update checks: 12 passed, 1 skipped (detached-supervisor acceptance
  runs only in its explicit Linux CI job). Rust formatting passed; 39 locked
  Rust unit tests and Clippy with warnings denied passed on Windows x64. The
  desktop cutover source guard and `git diff --check` passed at this revision.
- Current Windows x64 checks: `cargo fmt --check`, 39 locked Rust tests,
  Clippy with warnings denied, and locked release build passed. Focused
  transport/context/mutation tests passed 112; desktop install/controller tests
  passed 190; Caveman CLI tests passed 20.
- `tests/test_surface_benchmarks.py` passed 94/94 after correcting two benchmark
  cache verifiers to match their production cache keys. `release_check.py
  --allow-installed`, `compileall` for `src/tools/tests`, `selftest.py`, and the
  test-environment isolation module (3/3) passed.
- Fresh critical suite: 2,050 passed, 13 skipped, 1 failed. The failure was an
  obsolete assertion that `/dashboard` serves HTML. The test now checks the
  retired dashboard's HTTP 404 JSON and passes focused (1/1); the critical suite
  was not rerun after that test-only correction. The combined changed-module
  suite passed 417/417 after updating stale config fixtures and source-location
  assertions.
- The recorded full Python suite (17,839 passed, 975 failed, 63 errors, 148
  skipped) predates current fixes and is not a current full-suite receipt.
- The PR remains a draft. Full dashboard/CLI parity, complete CI, cross-platform
  interactive runtime, installer/update migration, security/performance review,
  and release acceptance remain open. No merge-readiness claim is made.

## Architecture (Rust revision)

The desktop is now compiled Rust, using eframe/egui 0.31.1 with the Glow
OpenGL renderer. No Tkinter, Qt, Electron, browser engine or local UI server.
The toolkit is MIT/Apache-2.0 licensed. The explicit 0.31.1 pin targets a
known App::update API, not a claim to be the newest release. Upgrade and
dependency license/security review remain release gates.

Build from a trusted Hub checkout with Rust stable and platform OpenGL
libraries: `cargo build --manifest-path desktop/Cargo.toml --release`.
Run `python tools/hubctl.py desktop`, or run `desktop/target/release/local-ai-hub-desktop` directly from the Hub root. Set LOCAL_AI_HUB_ROOT, LOCAL_AI_DESKTOP_PYTHON,
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
| `desktop` | Native launcher | Current entry point; `dashboard` alias removed; verify launch and missing binary error |
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


## Plan lifecycle, telemetry parity and online native smoke

- [Native CI at 44a76c3](https://github.com/Harfusha/local-ai-hub/actions/runs/45981310058) passed all four platform jobs, including 311 Python bridge tests and 28 Linux Rust tests. Linux first window: 0.104021 s; mean idle RSS 112,889,856 bytes (107.66 MiB); idle CPU 0.016667% of one core. Hub was absent.
- Main [CI at 44a76c3](https://github.com/Harfusha/local-ai-hub/actions/runs/45981310134): Linux 3.11 platform smoke 586 passed / 13 skipped; lint, typing and reported platform jobs passed. Critical regression cohort: 1120 passed / 6 skipped / one failed, the minimum context budget rejection lost its next-action guidance with diagnostics disabled. Scheduled full integration jobs were cancelled by newer pushes, not successful full-suite receipts.
- At the final MCP wire boundary, the specific context budget rejection now retains its actionable larger-budget instruction while fitting the actual response envelope, independently of diagnostic metadata. Exact artifact pointers take precedence; existing live MCP tests exercise both diagnostic modes. Fresh CI required.
- The desktop exposes canonical plan validation and revision-fenced archive, repository-wide board loading without a preselected card, and bounded server-side plan search and lifecycle filtering (including paused). Task create/edit/move/delete preflight checks exact revision and ID existence/absence, preventing accidental upserts. Expanded real two-root HTTP/IPC acceptance tests cover board loading, search, validation, stale archive, successful archive and isolation.
- Native runtime tables added for resident details, execution profiles, model/cache/agent/route statistics, and Laya capture. Laya summaries show reported advisory runtime, coverage, latency, category and baseline counts without manufacturing zero values. Metric scope and uncertain freshness are indicated; model comparison requires confirmation at both UI and IPC boundary.
- Long forms scroll independently of the response area; confirmation cannot replace an in-flight operation. Scope changes clear root-bound inputs. Failed operations invalidate stale snapshots and plan revisions.
- Linux smoke now supports an actual isolated online Hub, using the real LocalAIApp, ephemeral loopback port, temporary configuration/state, no inference or preprocessing, and a normal focused native window. It records first observed adapter readiness request, desktop-only CPU/RSS, sampled lower bounds for short-lived adapter children, and Hub readiness after desktop exit. CI runs both modes and uploads reports; no new measurement is claimed yet. Interactive Windows/macOS, full service supervisor start/stop/restart, accessibility, complete historical control/CLI parity and signed installer/release verification remain open.
- Direct checkout still fails DNS and Cargo is unavailable in the local editing environment. Active repository planner unavailable; no direct plan-store edits. Keep PR draft until new evidence supports acceptance.


## Native interaction hardening and transfer acceptance

- [Native CI at ed51d8a](https://github.com/Harfusha/local-ai-hub/actions/runs/45984018861): the bridge passed 325 tests; Windows and ARM64 macOS jobs succeeded. Intel macOS and main CI were superseded by subsequent pushes. Linux compiled and reached the X11 smoke, but the named window was observed before it was mapped and X_SetInputFocus returned BadMatch. The test now requires a viewable mapped window and retries focus within a bounded deadline; it still fails if focus cannot be established. No fresh online measurement is claimed.
- Navigation now discards selection, cursor, scope-dependent mutation input and configuration drafts rather than transferring them between views. Headless egui tests render all native views at minimum window size without an adapter, exercise navigation guards and worker failures, and verify archive password separation. These are native render/state tests, not interactive physical-device acceptance.
- The Tasks and Run history lists expose all canonical task statuses and 25/50/100/250-row pages. They use the reported next offset and a bounded back stack, invalidate old pages when filters change, reject malformed page metadata, and indicate incomplete bounded searches rather than guessing completeness.
- New live two-root HTTP/IPC cases exercise repository-scoped memory record, find, unauthorized cross-root delete, explicit confirmation, successful deletion and briefing. Timeline SQLite failure now reaches the existing retryable HTTP error boundary rather than masquerading as an empty terminal page. The legacy unpaged timeline contract is unchanged.
- ZIP import streams at most 64 KiB per read and announces a bounded Content-Length; short reads fail and growth cannot exceed the announced byte count. Validate ZIP signatures/central-directory markers without extracting content. Export requires a complete ZIP and removes invalid partial output. The encrypted support receipt does not put its password into generic search fields; reveal and copy are explicit. Server-side archive validation remains authoritative.
- Optional focused log following refreshes the bounded tail every five seconds and stops on navigation or error. It is not a gap-free stream. Ordinary successful reads no longer force an additional health-probe process; lifecycle operations still schedule a fresh probe.
- New tests and code require a completed CI run. Intermediate runs have been superseded by subsequent commits. Main critical regression, latest native matrix including real online smoke, real supervisor lifecycle, physical Windows/macOS interaction, accessibility, exhaustive CLI/historical UI equivalence and installer/release acceptance are not verified. The PR remains draft. Local Cargo, direct Git checkout DNS and active Hub planner are unavailable; no direct plan-store edits or merge.


## Memory and incident operations; real online Linux receipt

- [Native desktop at e217fe8](https://github.com/Harfusha/local-ai-hub/actions/runs/45985566845): all four platform builds/tests and the bridge passed (33 Rust tests per target, 339 Python tests). Linux mapped-window Xvfb smoke completed both offline and online. Offline first window 0.210276 s, desktop mean RSS 113,164,288 bytes, CPU 0.416666% of one core over 60 s. Online first window 0.107139 s, first adapter readiness request 0.568661 s, mean desktop RSS 111,034,368 bytes, CPU 4.466658% of one core over 60 s. Sampled bridge child CPU lower bound 0.83 s, sampled peak child RSS lower bound 45,084,672 bytes. Hub remained ready after desktop exit. These are single isolated software-rendered CI measurements, not physical-device or supervisor lifecycle acceptance.
- [Main CI at e217fe8](https://github.com/Harfusha/local-ai-hub/actions/runs/45985566755): Linux 3.11 platform cohort 586 passed / 13 skipped; lint and type checks passed. Critical cohort and full scheduled integrations were superseded. Windows 3.11 acceptance log revealed one failure in uninstall instruction cleanup due to missing canonical defaults in the temporary install fixture; corrected fixture without disabling the test.
- Native memory now supports exact scoped record retrieval, bounded key/text/status search and quarantine with a mandatory reason and positive identity/status receipt. Global promotion, worktree mutation and compaction are not exposed as unauthorized HTTP actions. The existing two-root HTTP/IPC acceptance test now checks cross-root rejection of get/quarantine and scoped quarantine search. Regression tests cover exact payload and malformed acknowledgements.
- Incident inventory supports server status filters and bounded results, separate negative-knowledge search and explicit recording of root cause and verified fix. A literal 'resolved' is not accepted as evidence of a fix. The bridge requires an actual incident receipt. Native tables keep provenance, record identity, confidence and reported resolution details visible.
- Removed the animated spinner from periodic health probes to avoid continuous GUI repaint while waiting. The next online measurement must verify the effect; no new CPU figure claimed.
- Latest commits need fresh verification. Complete historical UI/CLI parity, remaining critical/integration CI, real supervisor lifecycle, physical Windows/macOS interaction and accessibility, signed installer/release acceptance remain open. Local checkout/Cargo and the active planner are not available. PR remains draft; no direct plan-store writes or master merge.


## Task contracts, bounded IPC and owned supervisor lifecycle

- [Native desktop at 519150c](https://github.com/Harfusha/local-ai-hub/actions/runs/45986772510) passed all five jobs, including 358 Python bridge tests and 33 Rust tests on Linux. Linux isolated smoke: offline first window 1.978633 s, mean RSS 110,379,008 bytes, CPU 0.483332% of one core; online first window 0.211610 s, first readiness request 0.617146 s, mean RSS 109,264,896 bytes, CPU 0.516666% of one core, Hub ready after desktop exit. Compared with the preceding single online measurement (4.466658% CPU), the nonanimated probe is promising; the measurements are not a controlled hardware benchmark.
- [Main CI at 519150c](https://github.com/Harfusha/local-ai-hub/actions/runs/45986772228): all platform smoke jobs, lint, types and fast-contract passed. Critical regression tests: 1121 passed / 6 skipped; the coverage ratchet failed due to moved command broker and authorization implementations and shutdown coverage 8/12 versus 10/12. Scheduled full integrations were superseded. No claim of complete CI success.
- Coverage thresholds and historical baseline provenance remain unchanged. Explicit mappings bind the old command broker module threshold to the aggregate measured implementation modules and function thresholds to the actual authorization/run mixin methods, with required presence and fail-closed regression checks. New regression cases exercise missing/weak relocated measurements and shutdown timeout, retry, incomplete receipt and reentrant behavior. Fresh CI must verify the thresholds; no measured counts were invented.
- Desktop task contract creation now uses canonical AgentScope values, includes description, non-goals, constraints, critical risk and optional SLO JSON. Exact task IDs and expected state are required for successful mutations; transition cannot bypass completion receipts. Added real two-root HTTP/IPC task creation, filtered 25-row continuation, unauthorized task lookup, rejected completion without receipts, and incident recording/list/search isolation. The additional task rows are seeded in the real store, not simulated responses.
- Adapter stdout retention is bounded during streaming reads, with overflow rejection before JSON decoding and unused stderr discarded. This avoids allocating arbitrary stdout/stderr buffers; it is not a subprocess execution deadline. Native input guards reject submissions while a confirmation or installation dialog is active; failed workers clear stale settings/update revisions. Archive export uses exclusive creation with owner-only requested POSIX mode; this is not a Windows ACL guarantee.
- CLI stop no longer terminates a raw PID obtained from status HTTP. It requires the existing service controller's owned-shutdown acknowledgment and a non-autostart readiness check. A detached Linux/macOS supervisor without an installed user service is accepted only when the explicit missing-registration reason and all stopped-role/port receipts agree; failures remain failures. Added isolated Linux detached supervisor acceptance exercising IPC start, repeat start, confirmation rejection, restart, stop, repeat stop, exact process-owner records, readiness and port release. CI runs it separately, using a temporary home, state and ephemeral port with inference, preprocessing and MCP HTTP disabled. Registered OS service manager interaction and configuration binding across multiple real installations are not covered by this fixture.
- Latest changes need fresh CI. Full historical UI/CLI parity, platform-specific interactive accessibility and release/installer signing and acceptance remain incomplete. Local Cargo and direct checkout DNS were unavailable; the active Hub planner was unavailable; no direct plan-store writes or merge.


## Exact MCP source receipts, plan dependencies and cross-platform bridge gate

- [Native desktop at a98256c](https://github.com/Harfusha/local-ai-hub/actions/runs/45991184799) passed the four platform jobs and the Linux bridge, with 35 Rust tests on Linux, 369 Python tests passed / one opt-in test skipped, then the actual isolated supervisor lifecycle test passed separately. Linux online first window 0.212163 s, first adapter readiness request 0.624926 s, mean desktop RSS 108,986,368 bytes (103.94 MiB), mean desktop CPU 0.516666% of one core, service remained ready after desktop exit. Offline first window 0.318852 s, mean RSS 110,764,032 bytes, CPU 0.533332% of one core. These are single Linux/Xvfb measurements, not hardware portability claims.
- [Main CI at a98256c](https://github.com/Harfusha/local-ai-hub/actions/runs/45991184827): all reported platform smoke jobs, lint, typing and fast-contract passed. Critical regression tests 1138 passed / 6 skipped, coverage ratchet passed. The separate fresh source-symbol/citation goldset failed. Scheduled full integrations were superseded by new pushes, not successful receipts.
- The MCP extraction moved the seven actual public callable definitions out of mcp_server.py, while the goldset still expected exact AST definitions there. v3 follows all seven real callable source modules and retains all seven architecture targets, original query, k=7, exact AST/role/precision/recall requirements and historical v1 targets. Old v2 snapshots cannot be paired with the changed contract. Restored real callable docstrings, including three previously misplaced string literals, and added explicit per-case output and a CI artifact even on goldset failure. New checks verify actual source AST definitions. A fresh passing goldset result is not claimed.
- Plan metadata and task draft editing now support lifecycle (ordinary states only, archive separately), default Git target, accountable role, task kind, work phase, order and typed dependencies. Only explicit changed fields are sent, with exact canonical revision and bounded validation; server graph validation remains authoritative. Task creation preserves chosen dependency/kind values. Live two-root HTTP/IPC tests cover metadata edits, dependency cycle rejection, stale revision and isolation. Existing optional role cannot be cleared via an invalid null; omit unchanged fields.
- The task creation form can set an optional canonical session ID. A plan card can bind an existing real Agent OS task through the canonical endpoint only after reading the task's persisted session and requiring the observed plan revision. Exact root, task, plan and session receipts are required; the server enforces matching criteria. The live fixture tests confirmation, stale and foreign-root rejection and actual persisted binding.
- Bridge, packaging/installation contract and HTTP/IPC acceptance now run on Ubuntu, Windows, macOS ARM and Intel. Only the detached-supervisor fixture is Linux-only. This is not a claim that platform-specific interactive UI or registered-service tests passed.
- Rust bridge exchanges now have an absolute deadline (15 s probe, bounded reads, conservative mutation/long-operation limits), bounded stdout and independent pipe workers. A stuck bridge is reaped without killing the Hub or detached supervisor; unknown outcomes must be reconciled before retrying. A real nonresponsive subprocess regression exercises blocked input without a shell or Python dependency. Pipe-handle inheritance by other processes can delay pipe worker cleanup, but cannot block the UI worker indefinitely.
- Latest changes require fresh CI. No local Cargo or GitHub checkout DNS; active Hub planner unavailable. Remaining release gates: full latest main/native CI, complete historical UI/CLI equivalence, physical Windows/macOS interactions and accessibility, registered OS service lifecycle, signed installer/release acceptance. Keep the PR draft; no master merge or direct plan-store edits.


## Model administration, native input, exact instruction apply and distribution evidence

- [Native desktop at da04f26](https://github.com/Harfusha/local-ai-hub/actions/runs/45994031916) passed all eight jobs: 38 Rust tests, 377 Python bridge tests passed / one opt-in skip on each of Linux, Windows, macOS Intel and macOS ARM64, plus the Linux isolated supervisor lifecycle passed separately. Linux Xvfb with the Hub running: first window 0.210130 s, mean desktop RSS 108,961,792 bytes, CPU 0.499998% of one core, Hub ready after desktop exit. Offline first window 1.555538 s, mean RSS 110,966,921 bytes, CPU 0.483332%. These are individual measurements, not hardware-wide performance claims.
- [Main CI at da04f26](https://github.com/Harfusha/local-ai-hub/actions/runs/45994031976): 1140 critical regression tests passed / 6 skipped, coverage ratchet passed, v3 exact-source goldset passed, and six source-intent/entrypoint regressions passed. Lint, typing, fast-contract and platform smoke succeeded; full integration matrix not confirmed complete at inspection. No threshold was reduced.
- Added a distinct Ollama administration view (not a replacement for the provider-neutral and resident inventories). Pull/delete are explicitly confirmed, use the canonical authenticated admin endpoint, require enabled backend and exact receipt. Delete performs fresh exact-name non-resident inventory preflight; missing /ps is unknown, never unloaded, and no VRAM value is manufactured. This preflight is not an atomic reservation against another process loading a model between requests. A real HTTP/IPC test uses a bounded local Ollama protocol fixture with no external download or inference.
- Keyboard shortcuts F5, Command/Ctrl+F and Command/Ctrl+L, Escape cancellation, selected AccessKit label relationships, and bounded scrollable mutation confirmation now include exact model, execution, manifest and plan metadata. The confirmation excludes arbitrary image/secret payloads. This is not a complete screen-reader accessibility audit.
- Native smoke now has Win32 owned visible window detection and macOS CoreGraphics window ownership, foreground focus via the OS, actual isolated Hub readiness, and separate idle CPU/RSS samples. CI exercises offline and online modes for all four targets; no silent skip on missing interactive session. Linux also sends real F5 keyboard input and waits for the actual live-status HTTP route. These new checks have not yet passed at the current revision; runner display/activation support is a remaining gate.
- Instruction compression stages candidates, prints durable manifest paths, and offers exact review, apply and restore through both the CLI and native desktop. Source eligibility, explicit repository and configured staging folder, exact manifest digest, backup/candidate/source hashes, deterministic preservation and clean advisory semantic review are checked. Apply/restore do not invoke inference or regenerate text. Native side-by-side full text review is virtualized; no write without explicit consent. Source reads are bounded. Existing atomic file replacement does not provide an OS-wide lock against unrelated concurrent editors; reload on conflicts. CLI counts backup failures as failures. The old direct `--apply` compression path is removed; the current CLI uses staged candidates and explicit `--apply-caveman` only after successful semantic review.
- Portable archive format 2 includes project LICENSE, Cargo.lock and collected upstream dependency license/notice texts and expressions from actual locked Cargo metadata. Binary and evidence digests and exact SHA256SUMS are verified; the installer requires format 2 and rejects format 1. Missing upstream license texts are explicitly marked for review; this is not a legal compatibility verdict or code signature. No signing keys/certificates were available and no signed release is claimed.
- New contract and fixture tests need completed CI at the new head. No local Cargo or direct GitHub checkout DNS; active repository planner unavailable. Remaining acceptance gates include full latest main/native CI, exact remaining historical UI/CLI parity (including policy-constrained operations), physical OS/screen-reader and registered service manager acceptance, real signed release/installer and dependency legal/security review. PR remains draft; no direct plan-store edits, merge or release publication.


## Vision upload integrity

- The native vision form first inspects the selected file locally and exposes a bounded MIME/size/SHA-256 receipt; it does not call the Hub or send image bytes. The explicit send confirmation includes the digest. The bridge hashes the exact bytes it would submit and rejects missing or changed receipts before contacting the configured vision route. A descriptor-level regular-file check and bounded reads protect the inspection boundary. This is a byte-integrity check, not full image decoding or a guarantee about configured route privacy. Added regression tests for local inspection, missing consent/digest, changed bytes, exact payload and oversized files. Fresh native and Python CI are required; other outstanding parity and release gates remain open.
